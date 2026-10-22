"""Owner-only watch reports (README, "9.16"): UPI match, a bill's trail, the day's changes,
and the GST registration threshold."""

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query

from app.api.common import get_or_404, unprocessable
from app.api.deps import Caller, require_owner
from app.core.time import business_date
from app.models import Bill
from app.services import gstwatch, trail, upimatch, wasted

router = APIRouter(tags=["reports"])
MAX_DAYS = 31


@router.get("/reports/upi-match")
def upi_match(
    start: date | None = Query(default=None, alias="from"),
    end: date | None = Query(default=None, alias="to"),
    caller: Caller = Depends(require_owner),
) -> dict:
    end = end or business_date()
    start = start or end - timedelta(days=6)
    if end < start or (end - start).days >= MAX_DAYS:
        raise unprocessable("Pick a range of up to 31 days")
    return upimatch.build(caller.db, start, end)


@router.get("/bills/{bill_id}/trail")
def bill_trail(bill_id: uuid.UUID, caller: Caller = Depends(require_owner)) -> dict:
    bill = get_or_404(caller.db, Bill, bill_id)
    return {"invoice_no": bill.invoice_no, "status": bill.status.value,
            "facts": trail.bill_trail(caller.db, bill)}  # fmt: skip


@router.get("/reports/wasted")
def wasted_report(
    days: int = Query(default=28, ge=7, le=92), caller: Caller = Depends(require_owner)
) -> dict:
    """What was wasted in the last `days` days, by item, weekday and reason."""
    return wasted.build(caller.db, business_date(), days)


@router.get("/reports/changes")
def changes(day: date | None = Query(default=None, alias="date"),
            caller: Caller = Depends(require_owner)) -> dict:  # fmt: skip
    return trail.changes(caller.db, day or business_date())


@router.get("/reports/gst-watch")
def gst_watch(caller: Caller = Depends(require_owner)) -> dict:
    return gstwatch.build(caller.db)
