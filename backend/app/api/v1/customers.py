"""Customers, their visits and their khata (README, "Phase 6").

Staff can find a customer, see their visits and take a repayment at the counter
(that needs internet: only the server knows what is owed). The list of everyone
who owes is a report, for the owner.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.common import get_or_404
from app.api.deps import Caller, get_caller, require_owner
from app.core.time import business_date, utcnow
from app.models import Bill, CreditRepayment, Customer, Shift, User
from app.services import customers as service
from app.services.billing import credit_paise

router = APIRouter(tags=["customers"])


class RepaymentIn(BaseModel):
    id: uuid.UUID  # made on the tablet: a retry records it once
    amount_paise: Annotated[int, Field(ge=1, le=10_000_000)]
    mode: Literal["cash", "upi", "card"]
    shift_id: uuid.UUID | None = None
    note: Annotated[str, Field(max_length=200)] = ""


def _row(c: Customer, owed: dict) -> dict:
    return {"id": c.id, "name": c.name, "phone": c.phone, "outstanding_paise": owed.get(c.id, 0)}


@router.get("/customers")
def find(q: str = Query(default="", max_length=40), caller: Caller = Depends(get_caller)) -> dict:
    """Search by the start of the number or any part of the name."""
    found = service.search(caller.db, q)
    owed = service.outstanding(caller.db, [c.id for c in found])
    return {"customers": [_row(c, owed) for c in found]}


@router.get("/customers/{customer_id}")
def detail(customer_id: uuid.UUID, caller: Caller = Depends(get_caller)) -> dict:
    c = get_or_404(caller.db, Customer, customer_id)
    bills = caller.db.scalars(
        select(Bill).where(Bill.customer_id == c.id).order_by(Bill.sold_at.desc()).limit(100)
    ).all()
    names = dict(caller.db.execute(select(User.id, User.name)).all())
    repaid = caller.db.scalars(
        select(CreditRepayment)
        .where(CreditRepayment.customer_id == c.id)
        .order_by(CreditRepayment.at.desc())
    ).all()
    return {
        **_row(c, service.outstanding(caller.db, [c.id])),
        "visits": [
            {
                "bill_id": b.id,
                "invoice_no": b.invoice_no,
                "sold_at": b.sold_at,
                "total_paise": b.total_paise,
                "credit_paise": credit_paise(b),
                "status": b.status.value,
            }
            for b in bills
        ],
        "repayments": [
            {
                "id": r.id,
                "amount_paise": r.amount_paise,
                "mode": r.mode,
                "at": r.at,
                "by_name": names.get(r.received_by, ""),
                "note": r.note,
            }
            for r in repaid
        ],
    }


@router.post("/customers/{customer_id}/repayments")
def repay(customer_id: uuid.UUID, body: RepaymentIn, caller: Caller = Depends(get_caller)) -> dict:
    c = get_or_404(caller.db, Customer, customer_id)
    if caller.db.scalar(select(CreditRepayment).where(CreditRepayment.id == body.id)) is None:
        owed = service.outstanding(caller.db, [c.id]).get(c.id, 0)
        if body.amount_paise > owed:
            raise HTTPException(409, "more_than_owed")
        shift = None
        if body.shift_id:
            shift = caller.db.scalar(select(Shift).where(Shift.id == body.shift_id))
        now: datetime = utcnow()
        caller.db.add(
            CreditRepayment(
                id=body.id,
                customer_id=c.id,
                amount_paise=body.amount_paise,
                mode=body.mode,
                shift_id=shift.id if shift else None,
                received_by=caller.user.id,
                note=body.note,
                at=now,
                business_date=business_date(now),
            )
        )
        caller.db.commit()
    return _row(c, service.outstanding(caller.db, [c.id]))


@router.get("/reports/khata", tags=["reports"])
def khata(caller: Caller = Depends(require_owner)) -> dict:
    """Owner: everyone who owes, biggest first."""
    owed = {k: v for k, v in service.outstanding(caller.db).items() if v > 0}
    people = caller.db.scalars(select(Customer).where(Customer.id.in_(list(owed)))).all()
    rows = sorted((_row(c, owed) for c in people), key=lambda r: -r["outstanding_paise"])
    return {"customers": rows, "total_paise": sum(owed.values())}
