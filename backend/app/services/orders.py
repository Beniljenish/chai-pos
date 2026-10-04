"""Running orders (README, "Restaurant service").

reduce(): an order's state from its events. The same rules are in
frontend/src/lib/orders.ts; shared/order_cases.json pins the two together.

Events are applied in order of their time (`at`, the device clock), then id, so
two waiters adding to one table from two phones, offline, end up in the same
state everywhere once both have synced. Once settled or cancelled, an order
does not change.

ingest(): events from a device, idempotent by event id, like bills.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import business_date, utcnow
from app.models import (
    Bill,
    Device,
    DiningTable,
    Order,
    OrderEvent,
    OrderEventKind,
    OrderStatus,
    OrderType,
    User,
)

MAX_CLOCK_AHEAD = timedelta(minutes=10)  # same rule as bills
FINAL = ("settled", "cancelled")


# ---------------------------------------------------------------- the rules
def _instant(at) -> datetime:
    if isinstance(at, datetime):
        return at
    return datetime.fromisoformat(str(at).replace("Z", "+00:00"))


def _iso(at) -> str:
    return _instant(at).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def empty_state() -> dict:
    return {
        "order_type": "dine_in",
        "table_id": None,
        "covers": 0,
        "customer_name": "",
        "customer_phone": "",
        # The customer agreed to messages (receipt, "order ready") on that number.
        "message_ok": False,
        "note": "",
        "status": "open",
        "opened_at": None,
        "opened_by": None,
        "lines": [],
        "kots": [],
        "cancellations": [],
        "bill_prints": 0,
        "changed_after_bill": False,
        "bill_id": None,
        "settled_at": None,
        "cancel_reason": None,
        "last_at": None,
    }


def reduce(events: list[dict]) -> dict:
    """events: dicts with id, kind, at, by, data."""
    s = empty_state()
    opened = False
    for e in sorted(events, key=lambda e: (_instant(e["at"]), str(e["id"]))):
        if s["status"] in FINAL:
            break
        kind, d, at, by = str(e["kind"]), e.get("data") or {}, _iso(e["at"]), str(e["by"])
        lines = {ln["line_id"]: ln for ln in s["lines"]}
        if kind == "open":
            if opened:
                continue
            opened = True
            s["order_type"] = d.get("order_type", "dine_in")
            s["table_id"] = d.get("table_id")
            s["covers"] = int(d.get("covers") or 0)
            for k in ("customer_name", "customer_phone", "note"):
                s[k] = d.get(k) or ""
            s["message_ok"] = bool(d.get("message_ok")) and bool(s["customer_phone"])
            s["opened_at"], s["opened_by"] = at, by
        elif kind == "kot":
            new_ids = []
            for ln in d.get("lines", []):
                if ln["line_id"] in lines:
                    continue  # the same KOT line twice: kept once
                row = {
                    "line_id": ln["line_id"],
                    "kot_no": d.get("kot_no", ""),
                    "menu_item_id": ln["menu_item_id"],
                    "name": ln["name"],
                    "qty": int(ln["qty"]),
                    "cancelled_qty": 0,
                    "unit_price_paise": int(ln["unit_price_paise"]),
                    "gst_rate_bp": int(ln["gst_rate_bp"]),
                    "tax_inclusive": bool(ln["tax_inclusive"]),
                    "modifiers": ln.get("modifiers") or [],
                    "note": ln.get("note") or "",
                    "ready": False,
                    "added_after_bill": s["bill_prints"] > 0,
                }
                s["lines"].append(row)
                lines[row["line_id"]] = row
                new_ids.append(row["line_id"])
            if new_ids:
                s["kots"].append(
                    {"kot_no": d.get("kot_no", ""), "at": at, "by": by, "line_ids": new_ids}
                )
                if s["bill_prints"] > 0:
                    s["changed_after_bill"] = True
                    s["status"] = "open"
        elif kind == "cancel":
            ln = lines.get(d.get("line_id"))
            take = min(int(d.get("qty") or 0), ln["qty"]) if ln else 0
            if take <= 0:
                continue
            ln["qty"] -= take
            ln["cancelled_qty"] += take
            after = s["bill_prints"] > 0
            s["cancellations"].append(
                {
                    "line_id": ln["line_id"],
                    "name": ln["name"],
                    "qty": take,
                    "reason": d.get("reason") or "",
                    "at": at,
                    "by": by,
                    "after_bill": after,
                }
            )
            if after:
                s["changed_after_bill"] = True
                s["status"] = "open"
        elif kind == "move":
            s["table_id"] = d.get("table_id")
        elif kind == "details":
            if "covers" in d:
                s["covers"] = int(d["covers"] or 0)
            phone_before = s["customer_phone"]
            for k in ("customer_name", "customer_phone", "note"):
                if k in d:
                    s[k] = d[k] or ""
            # Consent belongs to the number it was given for: a new number without
            # a fresh "yes" is not messaged.
            if "message_ok" in d:
                s["message_ok"] = bool(d["message_ok"])
            elif s["customer_phone"] != phone_before:
                s["message_ok"] = False
            if not s["customer_phone"]:
                s["message_ok"] = False
        elif kind == "bill_printed":
            s["bill_prints"] += 1
            s["status"] = "billed"
        elif kind == "ready":
            for lid in d.get("line_ids", []):
                if lid in lines:
                    lines[lid]["ready"] = True
        elif kind == "settle":
            s["status"], s["bill_id"], s["settled_at"] = "settled", d.get("bill_id"), at
        elif kind == "cancel_order":
            s["status"], s["cancel_reason"] = "cancelled", d.get("reason") or ""
        else:
            continue
        s["last_at"] = at
    return s


# ---------------------------------------------------------------- ingest
@dataclass
class OrderContext:
    db: Session
    device: Device
    caller_id: uuid.UUID
    staff_ids: frozenset[uuid.UUID] = frozenset()
    now: datetime = field(default_factory=utcnow)

    def person(self, ev: dict) -> uuid.UUID:
        claimed = ev.get("by")
        return claimed if claimed in self.staff_ids else self.caller_id


def _hash(ev: dict) -> str:
    body = {k: ev[k] for k in ("id", "order_id", "kind", "at", "data")}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _clean(ctx: OrderContext, kind: str, data: dict) -> dict:
    """Drop references the shop does not own (a table of another shop): the
    event is kept, the reference is not."""
    if kind in ("open", "move") and data.get("table_id"):
        t = ctx.db.scalar(select(DiningTable).where(DiningTable.id == data["table_id"]))
        if t is None:
            data = {**data, "table_id": None}
    return data


def ingest(ctx: OrderContext, events: list[dict]) -> list[tuple[uuid.UUID, str, str | None]]:
    out: list[tuple[uuid.UUID, str, str | None]] = []
    touched: set[uuid.UUID] = set()
    for ev in events:
        digest = _hash(ev)
        existing = ctx.db.scalar(select(OrderEvent).where(OrderEvent.id == ev["id"]))
        if existing is not None:
            out.append(
                (ev["id"], "duplicate", None)
                if existing.content_hash == digest
                else (ev["id"], "rejected", "id_reused_with_different_content")
            )
            continue
        if ev["at"] > ctx.now + MAX_CLOCK_AHEAD:
            out.append((ev["id"], "rejected", "device_clock_ahead"))
            continue
        savepoint = ctx.db.begin_nested()
        try:
            order = ctx.db.scalar(select(Order).where(Order.id == ev["order_id"]))
            data = _clean(ctx, ev["kind"], dict(ev["data"]))
            if order is None:
                if ev["kind"] != "open":
                    savepoint.rollback()
                    out.append((ev["id"], "rejected", "unknown_order"))
                    continue
                order = Order(
                    id=ev["order_id"],
                    device_id=ctx.device.id,
                    order_type=OrderType(data.get("order_type", "dine_in")),
                    status=OrderStatus.open,
                    table_id=data.get("table_id"),
                    opened_by=ctx.person(ev),
                    opened_at=ev["at"],
                    business_date=business_date(ev["at"]),
                    state=empty_state(),
                )
                ctx.db.add(order)
                ctx.db.flush()
            ctx.db.add(
                OrderEvent(
                    id=ev["id"],
                    order_id=order.id,
                    kind=OrderEventKind(ev["kind"]),
                    data=data,
                    by=ctx.person(ev),
                    device_id=ctx.device.id,
                    at=ev["at"],
                    content_hash=digest,
                )
            )
            ctx.db.flush()
            savepoint.commit()
            touched.add(order.id)
            out.append((ev["id"], "accepted", None))
        except IntegrityError:
            savepoint.rollback()
            out.append((ev["id"], "rejected", "id_conflict"))
    from app.services import messages  # local: messages imports models only

    for oid in touched:
        messages.order_changed(ctx.db, recompute(ctx.db, oid))
    ctx.db.commit()
    return out


def recompute(db: Session, order_id: uuid.UUID) -> Order:
    order = db.scalar(select(Order).where(Order.id == order_id))
    evs = db.scalars(select(OrderEvent).where(OrderEvent.order_id == order_id)).all()
    state = reduce(
        [{"id": e.id, "kind": e.kind.value, "at": e.at, "by": e.by, "data": e.data} for e in evs]
    )
    order.state = state
    order.status = OrderStatus(state["status"])
    order.table_id = state["table_id"]
    order.order_type = OrderType(state["order_type"])
    order.updated_at = utcnow()
    return order


def live(db: Session, since: datetime | None) -> list[Order]:
    """Open and billed orders, plus any that changed since `since` (so a device
    learns that a table it shows was settled elsewhere)."""
    q = select(Order).where(Order.status.in_([OrderStatus.open, OrderStatus.billed]))
    rows = list(db.scalars(q))
    if since is not None:
        seen = {o.id for o in rows}
        rows += [
            o for o in db.scalars(select(Order).where(Order.updated_at > since)) if o.id not in seen
        ]
    return rows


# ---------------------------------------------------------------- owner report
def _line_value(line: dict, qty: int) -> int:
    """What `qty` of a line is worth at the price it was ordered."""
    each = int(line.get("unit_price_paise", 0)) + sum(
        int(m.get("price_delta_paise", 0)) for m in line.get("modifiers") or []
    )
    return each * qty


def service_report(db: Session, d: date) -> dict:
    """Owner: what happened at the tables on one business day. The leak signals are
    items cancelled after they were sent, bills changed after they were printed, and
    whole orders cancelled; each with who and why."""
    rows = db.scalars(select(Order).where(Order.business_date == d).order_by(Order.opened_at)).all()
    names = {str(k): v for k, v in db.execute(select(User.id, User.name)).all()}
    tables = {str(k): v for k, v in db.execute(select(DiningTable.id, DiningTable.name)).all()}
    bill_ids = [uuid.UUID(o.state["bill_id"]) for o in rows if o.state.get("bill_id")]
    invoices = (
        {
            str(k): v
            for k, v in db.execute(
                select(Bill.id, Bill.invoice_no).where(Bill.id.in_(bill_ids))
            ).all()
        }
        if bill_ids
        else {}
    )

    cancelled_by = {
        e.order_id: str(e.by)
        for e in db.scalars(
            select(OrderEvent).where(
                OrderEvent.kind == OrderEventKind.cancel_order,
                OrderEvent.order_id.in_([o.id for o in rows if o.status == OrderStatus.cancelled]),
            )
        )
    }

    def label(o: Order) -> str:
        s = o.state
        if o.order_type == OrderType.dine_in:
            return tables.get(str(s.get("table_id")), "No table")
        kind = "Takeaway" if o.order_type == OrderType.takeaway else "Delivery"
        return f"{kind}: {s['customer_name']}" if s.get("customer_name") else kind

    cancellations, changed, cancelled_orders, still_open = [], [], [], []
    counts = {"dine_in": 0, "takeaway": 0, "delivery": 0}
    for o in rows:
        s = o.state
        counts[o.order_type.value] += 1
        lines = {ln["line_id"]: ln for ln in s.get("lines", [])}
        for c in s.get("cancellations", []):
            ln = lines.get(c["line_id"], {})
            cancellations.append(
                {
                    "order_id": o.id,
                    "label": label(o),
                    "name": c["name"],
                    "qty": c["qty"],
                    "value_paise": _line_value(ln, c["qty"]),
                    "reason": c["reason"],
                    "by_name": names.get(c["by"], ""),
                    "at": c["at"],
                    "after_bill": c["after_bill"],
                }
            )
        if s.get("changed_after_bill"):
            changed.append(
                {
                    "order_id": o.id,
                    "label": label(o),
                    "bill_prints": s.get("bill_prints", 0),
                    "invoice_no": invoices.get(str(s.get("bill_id"))),
                    "removed": [
                        {"name": c["name"], "qty": c["qty"], "reason": c["reason"]}
                        for c in s.get("cancellations", [])
                        if c["after_bill"]
                    ],
                    "added": sum(
                        ln["qty"] for ln in s.get("lines", []) if ln.get("added_after_bill")
                    ),
                }
            )
        if o.status == OrderStatus.cancelled:
            # What was on the order when it was cancelled (lines not cancelled one by one).
            value = sum(_line_value(ln, ln["qty"]) for ln in s.get("lines", []))
            cancelled_orders.append(
                {
                    "order_id": o.id,
                    "label": label(o),
                    "reason": s.get("cancel_reason") or "",
                    "value_paise": value,
                    "by_name": names.get(cancelled_by.get(o.id, ""), ""),
                }
            )
        elif o.status in (OrderStatus.open, OrderStatus.billed):
            still_open.append({"order_id": o.id, "label": label(o), "status": o.status.value})
    return {
        "business_date": d,
        "orders": counts,
        "cancellations": cancellations,
        "cancelled_value_paise": sum(c["value_paise"] for c in cancellations),
        "changed_after_bill": changed,
        "cancelled_orders": cancelled_orders,
        "still_open": still_open,
    }
