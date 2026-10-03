"""Shifts and the cash drawer (README, "Shifts and cash").

Operations arrive from the tablet in the order they happened, possibly long
after (offline), possibly twice (a retry after a lost response). Each has an id
made on the tablet: the same operation twice is a harmless duplicate; a different
one under a used id is refused. Like bills, nothing here needs the server to be
reachable at the moment the cashier acts.

Expected cash in the drawer at the end of a shift:
    opening float + cash bills in the shift + paid in - paid out
Voided cash bills are left out of "cash bills" and listed beside it: whether the
money went back to the customer is something only the owner can judge.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import business_date, utcnow
from app.models import (
    Bill,
    BillStatus,
    CashMovement,
    CashMovementKind,
    Device,
    PaymentMode,
    Shift,
    User,
)

MAX_CLOCK_AHEAD = timedelta(minutes=10)  # same rule as bills
ACCEPTED, DUPLICATE, REJECTED = "accepted", "duplicate", "rejected"


@dataclass
class ShiftContext:
    db: Session
    device: Device
    caller_id: uuid.UUID
    staff_ids: frozenset[uuid.UUID] = frozenset()
    now: datetime = field(default_factory=utcnow)

    def person(self, op: dict) -> uuid.UUID:
        """Who did it: recorded on the tablet; anyone not in this shop falls back
        to the person syncing (same rule as bills)."""
        claimed = op.get("cashier_id")
        return claimed if claimed in self.staff_ids else self.caller_id


def ingest_ops(ctx: ShiftContext, ops: list[dict]) -> list[tuple[uuid.UUID, str, str | None]]:
    out = []
    for op in ops:
        if op["at"] > ctx.now + MAX_CLOCK_AHEAD:
            out.append((op["id"], REJECTED, "device_clock_ahead"))
            continue
        handler = {"open": _open, "cash": _cash, "close": _close}[op["op"]]
        savepoint = ctx.db.begin_nested()
        try:
            status, reason = handler(ctx, op)
            savepoint.commit()
        except IntegrityError:
            savepoint.rollback()
            # e.g. the id is used in another shop: say nothing about it.
            status, reason = REJECTED, "id_conflict"
        out.append((op["id"], status, reason))
    ctx.db.commit()
    return out


def _shift_of_this_device(ctx: ShiftContext, shift_id) -> Shift | None:
    s = ctx.db.scalar(select(Shift).where(Shift.id == shift_id))
    return s if s is not None and s.device_id == ctx.device.id else None


def _open(ctx: ShiftContext, op: dict):
    existing = ctx.db.scalar(select(Shift).where(Shift.id == op["id"]))
    if existing is not None:
        same = (
            existing.device_id == ctx.device.id
            and existing.opening_float_paise == op["opening_float_paise"]
            and existing.opened_at == op["at"]
        )
        return (DUPLICATE, None) if same else (REJECTED, "id_reused_with_different_content")
    ctx.db.add(
        Shift(
            id=op["id"],
            device_id=ctx.device.id,
            opened_by=ctx.person(op),
            opened_at=op["at"],
            business_date=business_date(op["at"]),
            opening_float_paise=op["opening_float_paise"],
        )
    )
    ctx.db.flush()
    return ACCEPTED, None


def _cash(ctx: ShiftContext, op: dict):
    existing = ctx.db.scalar(select(CashMovement).where(CashMovement.id == op["id"]))
    if existing is not None:
        same = existing.shift_id == op["shift_id"] and existing.amount_paise == op["amount_paise"]
        return (DUPLICATE, None) if same else (REJECTED, "id_reused_with_different_content")
    if _shift_of_this_device(ctx, op["shift_id"]) is None:
        return REJECTED, "unknown_shift"
    ctx.db.add(
        CashMovement(
            id=op["id"],
            shift_id=op["shift_id"],
            kind=op["kind"],
            amount_paise=op["amount_paise"],
            reason=op["reason"].strip(),
            created_by=ctx.person(op),
            at=op["at"],
        )
    )
    ctx.db.flush()
    return ACCEPTED, None


def _close(ctx: ShiftContext, op: dict):
    shift = _shift_of_this_device(ctx, op["shift_id"])
    if shift is None:
        return REJECTED, "unknown_shift"
    if shift.closed_at is not None:
        same = shift.counted_cash_paise == op["counted_cash_paise"]
        return (DUPLICATE, None) if same else (REJECTED, "already_closed")
    if op["at"] < shift.opened_at:
        return REJECTED, "closed_before_opened"
    shift.closed_at = op["at"]
    shift.closed_by = ctx.person(op)
    shift.counted_cash_paise = op["counted_cash_paise"]
    shift.close_note = op["note"].strip()
    ctx.db.flush()
    return ACCEPTED, None


# ---------------------------------------------------------------- reading
def device_state(db: Session, device_id: uuid.UUID) -> dict:
    """For a tablet starting up (or whose storage was wiped): its open shift, and
    the last count, which is the next person's opening float."""
    open_shift = db.scalar(
        select(Shift)
        .where(Shift.device_id == device_id, Shift.closed_at.is_(None))
        .order_by(Shift.opened_at.desc())
        .limit(1)
    )
    last = db.scalar(
        select(Shift)
        .where(Shift.device_id == device_id, Shift.closed_at.is_not(None))
        .order_by(Shift.closed_at.desc())
        .limit(1)
    )
    names = dict(db.execute(select(User.id, User.name)).all())
    return {
        "open_shift": None
        if open_shift is None
        else {
            "id": open_shift.id,
            "opened_by": open_shift.opened_by,
            "opened_by_name": names.get(open_shift.opened_by, ""),
            "opened_at": open_shift.opened_at,
            "opening_float_paise": open_shift.opening_float_paise,
        },
        "last_counted": None
        if last is None
        else {
            "counted_cash_paise": last.counted_cash_paise,
            "by_name": names.get(last.closed_by, ""),
            "at": last.closed_at,
        },
    }


def shift_report(db: Session, d: date) -> dict:
    shifts = db.scalars(
        select(Shift).where(Shift.business_date == d).order_by(Shift.opened_at)
    ).all()
    ids = [s.id for s in shifts]
    names = dict(db.execute(select(User.id, User.name)).all())
    devices = {dv.id: dv for dv in db.scalars(select(Device))}

    sales: dict = defaultdict(lambda: defaultdict(int))
    if ids:
        for b in db.scalars(select(Bill).where(Bill.shift_id.in_(ids))):
            t = sales[b.shift_id]
            if b.status == BillStatus.void:
                if b.payment_mode == PaymentMode.cash:
                    t["voided_cash"] += b.total_paise
                continue
            t["bills"] += 1
            t[b.payment_mode.value] += b.total_paise
    moves: dict = defaultdict(list)
    if ids:
        for m in db.scalars(
            select(CashMovement).where(CashMovement.shift_id.in_(ids)).order_by(CashMovement.at)
        ):
            moves[m.shift_id].append(m)

    rows = []
    for s in shifts:
        t = sales[s.id]
        paid_in = sum(m.amount_paise for m in moves[s.id] if m.kind == CashMovementKind.pay_in)
        paid_out = sum(m.amount_paise for m in moves[s.id] if m.kind == CashMovementKind.pay_out)
        expected = s.opening_float_paise + t["cash"] + paid_in - paid_out
        dv = devices.get(s.device_id)
        rows.append(
            {
                "id": s.id,
                "device": f"{dv.name} ({dv.code})" if dv else "",
                "opened_by_name": names.get(s.opened_by, ""),
                "opened_at": s.opened_at,
                "closed_by_name": names.get(s.closed_by, "") if s.closed_by else None,
                "closed_at": s.closed_at,
                "opening_float_paise": s.opening_float_paise,
                "bills": t["bills"],
                "cash_paise": t["cash"],
                "upi_paise": t["upi"],
                "card_paise": t["card"],
                "voided_cash_paise": t["voided_cash"],
                "paid_in_paise": paid_in,
                "paid_out_paise": paid_out,
                "movements": [
                    {
                        "kind": m.kind.value,
                        "amount_paise": m.amount_paise,
                        "reason": m.reason,
                        "by_name": names.get(m.created_by, ""),
                        "at": m.at,
                    }
                    for m in moves[s.id]
                ],
                "expected_cash_paise": expected,
                "counted_cash_paise": s.counted_cash_paise,
                # + over, - short; None while the shift is still open
                "difference_paise": None
                if s.counted_cash_paise is None
                else s.counted_cash_paise - expected,
                "close_note": s.close_note,
            }
        )
    outside = db.scalars(
        select(Bill).where(
            Bill.business_date == d,
            Bill.shift_id.is_(None),
            Bill.status != BillStatus.void,
            Bill.payment_mode == PaymentMode.cash,
        )
    ).all()
    return {
        "business_date": d,
        "shifts": rows,
        # Cash bills in no shift (an app from before shifts, or shifts switched off).
        "cash_outside_shifts": {
            "bills": len(outside),
            "total_paise": sum(b.total_paise for b in outside),
        },
    }
