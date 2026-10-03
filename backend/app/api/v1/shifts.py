"""Shifts and the cash drawer: sync from tablets, report for the owner."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.common import get_or_404
from app.api.deps import Caller, get_caller, require_owner
from app.core.time import business_date
from app.models import Device, User
from app.schemas_shifts import ShiftOpResult, ShiftSyncRequest, ShiftSyncResponse
from app.services import shifts

router = APIRouter(tags=["shifts"])


@router.post("/sync/shifts", response_model=ShiftSyncResponse)
def sync_shifts(body: ShiftSyncRequest, caller: Caller = Depends(get_caller)):
    """Shift starts, paid in / paid out and shift ends, made on the tablet (offline
    if need be). Always 200 with a result per operation, like bills."""
    device = get_or_404(caller.db, Device, body.device_id)  # tenant-scoped
    if not device.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This device has been deactivated")
    ctx = shifts.ShiftContext(
        db=caller.db,
        device=device,
        caller_id=caller.user.id,
        staff_ids=frozenset(caller.db.scalars(select(User.id))),
    )
    results = shifts.ingest_ops(ctx, [op.model_dump() for op in body.ops])
    return ShiftSyncResponse(
        results=[ShiftOpResult(id=i, status=s, reason=r) for i, s, r in results]
    )


@router.get("/shifts", tags=["reports"])
def shift_report(
    day: date | None = Query(default=None, alias="business_date"),
    caller: Caller = Depends(require_owner),
) -> dict:
    return shifts.shift_report(caller.db, day or business_date())
