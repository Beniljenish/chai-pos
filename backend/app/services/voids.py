"""Voiding a bill: the owner cancels a sale that should not count.

Rules (README, "Voids and the sales report"):
- Owner only (the API enforces it). A cashier who can void a cash bill can keep
  the cash and erase the sale.
- The bill itself is never edited or deleted: a BillVoid row records who, when and
  why, and the bill's status flag turns to "void". The invoice number stays used.
- Stock comes back by mirroring the bill's own sale rows (so Large / Less sugar
  come back exactly as they went out), unless the drink was already made.
- Not once the bill's day is approved: the count froze that day's numbers, and a
  void would quietly unbalance them. Correcting a closed day needs a credit note.
"""

import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Bill, BillStatus, BillVoid, LedgerReason, Shop, StockLedger, VoidReason
from app.models.dayend import DayCount, DayCountStatus


class VoidError(ValueError):
    pass


class AlreadyVoided(VoidError):
    pass


class DayClosed(VoidError):
    pass


def lock_day(db: Session, bdate) -> None:
    """Serialise voids and the day's approval: approval freezes the ledger at one
    instant, so a void must land wholly before it or be refused after it.
    Transaction-scoped; released on commit or rollback."""
    shop_id = db.scalar(select(Shop.id))  # the current tenant's shop
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"day:{shop_id}:{bdate}"))))


def void_bill(
    db: Session,
    bill_id: uuid.UUID,
    *,
    reason: VoidReason,
    note: str,
    drink_was_made: bool,
    user_id: uuid.UUID,
) -> BillVoid:
    bill = db.scalar(select(Bill).where(Bill.id == bill_id).with_for_update())
    if bill is None:
        raise LookupError(bill_id)
    lock_day(db, bill.business_date)
    if bill.status == BillStatus.void:
        raise AlreadyVoided("This bill is already voided")
    day = db.scalar(select(DayCount).where(DayCount.business_date == bill.business_date))
    if day is not None and day.status == DayCountStatus.approved:
        raise DayClosed(
            "This day is closed (count approved), so its bills can no longer be voided. "
            "Its stock and sales were already settled by the count."
        )

    v = BillVoid(
        bill_id=bill.id,
        reason=reason,
        note=note.strip(),
        stock_returned=not drink_was_made,
        voided_by=user_id,
    )
    db.add(v)
    bill.status = BillStatus.void

    if not drink_was_made:
        sold: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
        for ingredient_id, qty in db.execute(
            select(StockLedger.ingredient_id, StockLedger.qty_delta).where(
                StockLedger.ref_type == "bill",
                StockLedger.ref_id == bill.id,
                StockLedger.reason == LedgerReason.sale,
            )
        ):
            sold[ingredient_id] += qty
        for ingredient_id, qty in sorted(sold.items()):
            if qty:
                db.add(
                    StockLedger(
                        ingredient_id=ingredient_id,
                        qty_delta=-qty,  # sale rows are negative; this puts it back
                        reason=LedgerReason.void,
                        ref_type="bill",
                        ref_id=bill.id,
                        business_date=bill.business_date,  # the day it was sold
                        created_by=user_id,
                    )
                )
    db.flush()
    return v
