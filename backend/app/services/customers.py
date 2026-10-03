"""Customers and their khata (README, "Phase 6").

What a customer owes is never stored: it is the credit parts of their bills that
are not void, minus what they repaid. A voided credit bill therefore stops being
owed by itself, and nothing can drift out of step.
"""

import uuid
from collections import defaultdict

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Bill, BillStatus, CreditRepayment, Customer
from app.services.billing import credit_paise


def outstanding(db: Session, ids: list[uuid.UUID] | None = None) -> dict[uuid.UUID, int]:
    """Customer id -> paise owed (only customers with any credit or repayment)."""
    owed: dict[uuid.UUID, int] = defaultdict(int)
    q = select(Bill).where(Bill.customer_id.is_not(None), Bill.status != BillStatus.void)
    if ids is not None:
        q = q.where(Bill.customer_id.in_(ids))
    for b in db.scalars(q):
        owed[b.customer_id] += credit_paise(b)
    r = select(CreditRepayment.customer_id, func.sum(CreditRepayment.amount_paise)).group_by(
        CreditRepayment.customer_id
    )
    if ids is not None:
        r = r.where(CreditRepayment.customer_id.in_(ids))
    for cid, paid in db.execute(r):
        owed[cid] -= int(paid)
    return dict(owed)


def search(db: Session, q: str, limit: int = 20) -> list[Customer]:
    q = q.strip()
    if not q:
        return []
    digits = "".join(ch for ch in q if ch.isdigit())
    cond = Customer.name.ilike(f"%{q}%")
    if digits:
        cond = or_(cond, Customer.phone.startswith(digits))
    return list(db.scalars(select(Customer).where(cond).order_by(Customer.name).limit(limit)))
