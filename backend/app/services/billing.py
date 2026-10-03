"""Ingest bills from billing devices: online and offline sales use this one path.

Guarantees, per bill:
- Idempotent: the device-generated bill id is the key. Resending a bill is a
  harmless "duplicate"; resending a DIFFERENT bill under the same id is rejected.
- All-or-nothing: the bill, its lines and its stock deductions are saved in one
  savepoint. One bad bill never blocks the rest of the batch.
- Accept-and-flag: the printed totals are the legal record and are stored as-is.
  The server recalculates independently and flags any difference.
- Stock is deducted with the recipe VERSION the device sold under.
"""

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import business_date, utcnow
from app.models import (
    Bill,
    BillLine,
    BillLineModifier,
    Device,
    Ingredient,
    LedgerReason,
    MenuItem,
    Modifier,
    Recipe,
    Shop,
    StockLedger,
)
from app.services import gst
from app.services.recipes import Q3

MAX_CLOCK_AHEAD = timedelta(minutes=10)
MAX_BILL_AGE = timedelta(days=30)


class Outcome(StrEnum):
    accepted = "accepted"
    duplicate = "duplicate"
    rejected = "rejected"


@dataclass
class Result:
    id: uuid.UUID
    status: Outcome
    invoice_no: str | None = None
    totals_mismatch: bool = False
    reason: str | None = None


class Reject(Exception):  # noqa: N818  (control flow, not an error condition)
    pass


# ---------- pure helpers ----------
def financial_year(d: date) -> str:
    """Indian FY runs April to March: 3 Oct 2026 -> "26-27", 15 Feb 2027 -> "26-27"."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def invoice_number(device_code: str, fy: str, seq: int) -> str:
    return f"{device_code}/{fy}/{seq:06d}"


def content_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _totals_dict(t: gst.BillTotals) -> dict:
    return {
        "taxable": t.taxable,
        "cgst": t.cgst,
        "sgst": t.sgst,
        "subtotal": t.subtotal,
        "round_off": t.round_off,
        "total": t.total,
        "lines": [
            {
                "gross": lt.gross,
                "taxable": lt.taxable,
                "cgst": lt.cgst,
                "sgst": lt.sgst,
                "total": lt.total,
            }
            for lt in t.lines
        ],
    }


# ---------- the ingest ----------
@dataclass
class SyncContext:
    db: Session
    shop: Shop
    device: Device
    cashier_id: uuid.UUID  # who is syncing: the fallback when a bill names no one
    now: datetime = field(default_factory=utcnow)
    # Everyone in this shop, active or not: a cashier deactivated today still
    # had their offline bills from this morning credited to them.
    staff_ids: frozenset[uuid.UUID] = frozenset()

    def cashier_for(self, b: dict) -> uuid.UUID:
        """Who rang the bill up. The tablet records it at sale time, because
        another person may be logged in by the time it syncs. An id from another
        shop (a bug, or a tampered tablet) falls back to the person syncing."""
        claimed = b.get("cashier_id")
        return claimed if claimed in self.staff_ids else self.cashier_id


def ingest_batch(ctx: SyncContext, bills: list[dict]) -> list[Result]:
    """`bills` are validated request dicts (see schemas_billing.SyncBillIn.model_dump)."""
    results = [_ingest_one(ctx, b) for b in bills]
    ctx.device.last_seen_at = ctx.now
    ctx.db.commit()
    return results


def _ingest_one(ctx: SyncContext, b: dict) -> Result:
    bill_id = b["id"]
    digest = content_hash(b)

    existing = ctx.db.scalar(select(Bill).where(Bill.id == bill_id))
    if existing is not None:
        return _duplicate_or_conflict(existing, digest)

    savepoint = ctx.db.begin_nested()
    try:
        bill = _build_bill(ctx, b, digest)
        ctx.db.add(bill)
        ctx.db.flush()
        _deduct_stock(ctx, bill, b)
        ctx.db.flush()
        savepoint.commit()
        # Same transaction as the bill: the email exists if and only if the bill does.
        from app.services.reports import enqueue_bill  # local: reports imports billing

        enqueue_bill(ctx.db, ctx.shop, bill)
        return Result(bill_id, Outcome.accepted, bill.invoice_no, bill.totals_mismatch)
    except Reject as e:
        savepoint.rollback()
        return Result(bill_id, Outcome.rejected, reason=str(e))
    except IntegrityError as e:
        savepoint.rollback()
        return _after_integrity_error(ctx, bill_id, digest, e)


def _duplicate_or_conflict(existing: Bill, digest: str) -> Result:
    if existing.content_hash == digest:
        return Result(existing.id, Outcome.duplicate, existing.invoice_no, existing.totals_mismatch)
    return Result(existing.id, Outcome.rejected, reason="id_reused_with_different_content")


def _after_integrity_error(ctx: SyncContext, bill_id, digest, err: IntegrityError) -> Result:
    # A concurrent sync of the same bill may have won the race: re-check.
    existing = ctx.db.scalar(select(Bill).where(Bill.id == bill_id))
    if existing is not None:
        return _duplicate_or_conflict(existing, digest)
    msg = str(err.orig)
    if "uq_bills_device_seq" in msg or "uq_bills_invoice_no" in msg:
        return Result(bill_id, Outcome.rejected, reason="invoice_number_already_used")
    if "uq_bills_order_id" in msg:
        # Two tablets settled the same table: the first invoice stands.
        return Result(bill_id, Outcome.rejected, reason="order_already_billed")
    # e.g. the id collides with a row in ANOTHER shop: say nothing about it.
    return Result(bill_id, Outcome.rejected, reason="id_conflict")


def _shift_for(ctx: SyncContext, b: dict) -> uuid.UUID | None:
    """The bill's drawer shift, if it is a shift of this tablet. Shifts are sent
    before bills, so it is normally here; if not (it was refused), the bill is
    still accepted and shows as cash outside any shift."""
    from app.models import Shift  # local: models import order

    sid = b.get("shift_id")
    if sid is None:
        return None
    s = ctx.db.scalar(select(Shift).where(Shift.id == sid))
    return sid if s is not None and s.device_id == ctx.device.id else None


def _order_for(ctx: SyncContext, b: dict) -> uuid.UUID | None:
    """The running order this bill settles, if it is this shop's. Order events are
    sent before bills; a bill whose order never arrived is still accepted."""
    from app.models import Order  # local: models import order

    oid = b.get("order_id")
    if oid is None:
        return None
    return oid if ctx.db.scalar(select(Order.id).where(Order.id == oid)) else None


def _build_bill(ctx: SyncContext, b: dict, digest: str) -> Bill:
    sold_at: datetime = b["sold_at"]
    if sold_at > ctx.now + MAX_CLOCK_AHEAD:
        raise Reject("device_clock_ahead")
    if sold_at < ctx.now - MAX_BILL_AGE:
        raise Reject("bill_too_old")

    bdate = business_date(sold_at)
    fy = financial_year(bdate)
    expected_no = invoice_number(ctx.device.code, fy, b["local_seq"])
    if b["invoice_no"] != expected_no:
        raise Reject(f"invoice_no_mismatch: expected {expected_no}")

    lines_in = b["lines"]
    items = _load(ctx.db, MenuItem, {ln["menu_item_id"] for ln in lines_in}, "unknown_menu_item")
    recipe_ids = {ln["recipe_id"] for ln in lines_in if ln["recipe_id"]}
    recipes = _load(ctx.db, Recipe, recipe_ids, "unknown_recipe")
    mod_ids = {m["modifier_id"] for ln in lines_in for m in ln["modifiers"]}
    _load(ctx.db, Modifier, mod_ids, "unknown_modifier")
    snapshot_ingredients = {
        ml["ingredient_id"] for ln in lines_in for m in ln["modifiers"] for ml in m["lines"]
    }
    _load(ctx.db, Ingredient, snapshot_ingredients, "unknown_ingredient")

    for ln in lines_in:
        rid = ln["recipe_id"]
        if rid and recipes[rid].menu_item_id != ln["menu_item_id"]:
            raise Reject("recipe_not_for_menu_item")
    del items  # existence check only: names and prices come from the printed snapshot

    # The server's own calculation, from the same lines, under the shop's CURRENT
    # GST registration. A shop that changed registration while a device was
    # offline will therefore show up as a mismatch, which is what we want.
    try:
        server = gst.compute_bill(
            [
                gst.LineIn(
                    unit_price_paise=ln["unit_price_paise"],
                    qty=ln["qty"],
                    gst_rate_bp=ln["gst_rate_bp"],
                    tax_inclusive=ln["tax_inclusive"],
                    modifier_deltas_paise=tuple(m["price_delta_paise"] for m in ln["modifiers"]),
                )
                for ln in lines_in
            ],
            ctx.shop.gst_type,
        )
    except gst.GstError as e:
        raise Reject(f"invalid_line: {e}") from None
    server_totals = _totals_dict(server)
    printed = b["totals"]
    printed_lines = [ln["totals"] for ln in lines_in]
    mismatch = (
        any(printed[k] != server_totals[k] for k in printed)
        or printed_lines != server_totals["lines"]
    )

    bill = Bill(
        id=b["id"],
        device_id=ctx.device.id,
        cashier_id=ctx.cashier_for(b),
        shift_id=_shift_for(ctx, b),
        order_id=_order_for(ctx, b),
        fy=fy,
        local_seq=b["local_seq"],
        invoice_no=expected_no,
        sold_at=sold_at,
        business_date=bdate,
        payment_mode=b["payment_mode"],
        gst_type=b["gst_type"],
        taxable_paise=printed["taxable"],
        cgst_paise=printed["cgst"],
        sgst_paise=printed["sgst"],
        subtotal_paise=printed["subtotal"],
        round_off_paise=printed["round_off"],
        total_paise=printed["total"],
        server_totals=server_totals,
        totals_mismatch=mismatch,
        content_hash=digest,
    )
    for pos, ln in enumerate(lines_in, start=1):
        t = ln["totals"]
        line = BillLine(
            position=pos,
            menu_item_id=ln["menu_item_id"],
            recipe_id=ln["recipe_id"],
            name_snapshot=ln["name"],
            unit_price_paise=ln["unit_price_paise"],
            qty=ln["qty"],
            gst_rate_bp=ln["gst_rate_bp"],
            tax_inclusive=ln["tax_inclusive"],
            gross_paise=t["gross"],
            taxable_paise=t["taxable"],
            cgst_paise=t["cgst"],
            sgst_paise=t["sgst"],
            total_paise=t["total"],
        )
        line.modifiers = [
            BillLineModifier(
                modifier_id=m["modifier_id"],
                name_snapshot=m["name"],
                price_delta_paise=m["price_delta_paise"],
                scale_factor=m["scale_factor"],
                lines_snapshot=[
                    {"ingredient_id": str(ml["ingredient_id"]), "qty_delta": str(ml["qty_delta"])}
                    for ml in m["lines"]
                ],
            )
            for m in ln["modifiers"]
        ]
        bill.lines.append(line)
    return bill


def _load(db: Session, model, ids: set, reason: str) -> dict:
    if not ids:
        return {}
    rows = db.scalars(select(model).where(model.id.in_(ids))).all()  # tenant-scoped
    if len(rows) != len(ids):
        raise Reject(reason)
    return {r.id: r for r in rows}


def consumption_for_line(
    recipe_lines: dict[uuid.UUID, Decimal],
    qty: int,
    modifiers: list[dict],
    fixed: Collection[uuid.UUID] = frozenset(),
) -> dict[uuid.UUID, Decimal]:
    """Ingredients used by `qty` units of one line.

    per unit = recipe x (product of modifier scale factors) + sum of modifier deltas
    Ingredients in `fixed` (packaging: cups, lids) are not scaled: a Large tea
    still uses one cup. Modifier deltas still apply to them, which is how a
    "Large" can swap a regular cup (-1) for a large cup (+1).
    An ingredient never goes below zero use: "Less sugar" on a drink whose recipe
    has no loose sugar must not ADD sugar back into stock.
    """
    scale = Decimal(1)
    for m in modifiers:
        scale *= Decimal(m["scale_factor"])
    per_unit: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for ingredient_id, q in recipe_lines.items():
        per_unit[ingredient_id] += q if ingredient_id in fixed else q * scale
    for m in modifiers:
        for ml in m["lines"]:
            per_unit[ml["ingredient_id"]] += Decimal(ml["qty_delta"])
    return {i: (max(q, Decimal(0)) * qty).quantize(Q3) for i, q in per_unit.items() if q > 0}


def _deduct_stock(ctx: SyncContext, bill: Bill, b: dict) -> None:
    recipe_ids = {ln["recipe_id"] for ln in b["lines"] if ln["recipe_id"]}
    recipes = (
        {
            r.id: {rl.ingredient_id: rl.qty for rl in r.lines}
            for r in ctx.db.scalars(select(Recipe).where(Recipe.id.in_(recipe_ids)))
        }
        if recipe_ids
        else {}
    )
    used = {i for lines in recipes.values() for i in lines}
    fixed = (
        set(
            ctx.db.scalars(
                select(Ingredient.id).where(
                    Ingredient.id.in_(used), Ingredient.scales_with_size.is_(False)
                )
            )
        )
        if used
        else set()
    )

    total: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for ln in b["lines"]:
        recipe_lines = recipes.get(ln["recipe_id"], {})
        for ingredient_id, q in consumption_for_line(
            recipe_lines, ln["qty"], ln["modifiers"], fixed
        ).items():
            total[ingredient_id] += q

    # One ledger row per ingredient per bill, so a bill's effect is easy to audit
    # (and to reverse exactly when voids arrive in Phase 3).
    for ingredient_id, q in sorted(total.items()):
        if q:
            ctx.db.add(
                StockLedger(
                    ingredient_id=ingredient_id,
                    qty_delta=-q,
                    reason=LedgerReason.sale,
                    ref_type="bill",
                    ref_id=bill.id,
                    business_date=bill.business_date,
                    created_by=bill.cashier_id,
                )
            )
    # A bill from a day the owner already closed: its stock was gone before the
    # count, so keep stock on hand equal to that count (see dayend.py).
    from app.services.dayend import late_bill_correction  # local: dayend imports billing

    late_bill_correction(ctx.db, bill.business_date, total, bill.id, bill.cashier_id)
