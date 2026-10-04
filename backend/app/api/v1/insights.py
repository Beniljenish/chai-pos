"""Owner reports over more than one day, and stock valuation (README, "Phase 7")."""

from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.common import unprocessable
from app.api.deps import Caller, require_owner
from app.services import insights

router = APIRouter(tags=["reports"])


@router.get("/reports/range")
def sales_range(
    start: date = Query(alias="from"),
    end: date = Query(alias="to"),
    caller: Caller = Depends(require_owner),
) -> dict:
    try:
        return insights.range_report(caller.db, start, end)
    except insights.ReportError as e:
        raise unprocessable(str(e)) from None


@router.get("/reports/gst")
def gst(month: str = Query(max_length=7), caller: Caller = Depends(require_owner)) -> dict:
    """One month in GSTR-1 shape (B2C by rate, HSN summary, documents issued)."""
    try:
        return insights.gst_summary(caller.db, month)
    except insights.ReportError as e:
        raise unprocessable(str(e)) from None


@router.get("/reports/stock-value")
def stock_value(caller: Caller = Depends(require_owner)) -> dict:
    return insights.stock_value(caller.db)
