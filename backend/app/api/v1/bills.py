import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.common import get_or_404
from app.api.deps import Caller, get_caller, require_owner
from app.core.time import business_date
from app.models import Bill, BillLine, BillVoid, Device, Role, Shop, User
from app.schemas_billing import BillOut, SyncRequest, SyncResponse, SyncResultOut, VoidIn
from app.services import billing, email, voids
from app.services.sales import sales_report

router = APIRouter(tags=["bills"])


@router.post("/sync/bills", response_model=SyncResponse)
def sync_bills(body: SyncRequest, caller: Caller = Depends(get_caller)):
    """The ONLY way bills are created, online or offline. Always 200 with a result
    per bill; the device drops accepted/duplicate bills from its outbox and keeps
    rejected ones visible for the owner."""
    device = get_or_404(caller.db, Device, body.device_id)  # tenant-scoped
    if not device.is_active:
        # Not a 404: the device is ours, but the owner has switched it off.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This device has been deactivated")
    shop = caller.db.scalar(select(Shop))
    ctx = billing.SyncContext(
        db=caller.db,
        shop=shop,
        device=device,
        cashier_id=caller.user.id,
        staff_ids=frozenset(caller.db.scalars(select(User.id))),  # tenant-scoped
    )
    results = billing.ingest_batch(ctx, [_as_received(b) for b in body.bills])
    email.deliver_pending(caller.db)  # bill emails, if switched on; never raises
    return SyncResponse(
        results=[
            SyncResultOut(
                id=r.id,
                status=r.status,
                invoice_no=r.invoice_no,
                totals_mismatch=r.totals_mismatch,
                reason=r.reason,
            )
            for r in results
        ]
    )


@router.get("/devices/{device_id}/sync-state", tags=["devices"])
def device_sync_state(device_id: uuid.UUID, caller: Caller = Depends(get_caller)) -> dict:
    """The highest invoice sequence the server holds for this device, per financial
    year. A tablet whose storage was wiped resumes numbering after it instead of
    reissuing C1/26-27/000001 (which the server would reject as a duplicate)."""
    device = get_or_404(caller.db, Device, device_id)
    rows = caller.db.execute(
        select(Bill.fy, func.max(Bill.local_seq))
        .where(Bill.device_id == device.id)
        .group_by(Bill.fy)
    ).all()
    return {
        "device_id": device.id,
        "code": device.code,
        "is_active": device.is_active,
        "last_seq_by_fy": {fy: seq for fy, seq in rows},
    }


def _as_received(b) -> dict:
    """The bill as the tablet sent it. An app from before `cashier_id` existed
    did not send the key: leave it out rather than add null, or a retry of such
    a bill would hash differently and be refused as altered."""
    d = b.model_dump()
    if d.get("cashier_id") is None:
        d.pop("cashier_id", None)
    return d


def _bill_query():
    return select(Bill).options(
        selectinload(Bill.lines).selectinload(BillLine.modifiers),
        selectinload(Bill.void).selectinload(BillVoid.user),
    )


@router.get("/bills", response_model=list[BillOut])
def list_bills(
    day: date | None = Query(default=None, alias="business_date"),
    mismatch_only: bool = False,
    caller: Caller = Depends(get_caller),
):
    # Cashiers see today's bills only; owners can pick any date.
    if caller.ctx.role != Role.owner or day is None:
        day = business_date()
    q = _bill_query().where(Bill.business_date == day).order_by(Bill.sold_at)
    if mismatch_only:
        q = q.where(Bill.totals_mismatch)
    return caller.db.scalars(q).all()


@router.get("/bills/{bill_id}", response_model=BillOut)
def get_bill(bill_id: uuid.UUID, caller: Caller = Depends(get_caller)):
    bill = caller.db.scalar(_bill_query().where(Bill.id == bill_id))
    if bill is None:
        get_or_404(caller.db, Bill, bill_id)  # raises the standard 404
    return bill


@router.post("/bills/{bill_id}/void", response_model=BillOut)
def void_bill(bill_id: uuid.UUID, body: VoidIn, caller: Caller = Depends(require_owner)):
    """Owner only. Needs internet: the server must check the day is still open."""
    get_or_404(caller.db, Bill, bill_id)
    try:
        voids.void_bill(
            caller.db,
            bill_id,
            reason=body.reason,
            note=body.note,
            drink_was_made=body.drink_was_made,
            user_id=caller.user.id,
        )
    except voids.VoidError as e:
        caller.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    caller.db.commit()
    caller.db.expire_all()
    return caller.db.scalar(_bill_query().where(Bill.id == bill_id))


@router.get("/reports/sales", tags=["reports"])
def sales(
    day: date | None = Query(default=None, alias="business_date"),
    caller: Caller = Depends(require_owner),
) -> dict:
    return sales_report(caller.db, day or business_date())
