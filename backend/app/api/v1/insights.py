"""Owner reports over more than one day, and stock valuation (README, "Phase 7")."""

from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.common import unprocessable
from app.api.deps import Caller, require_owner
from app.services import alerts, insights, margin

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


@router.get("/reports/margin")
def item_margin(caller: Caller = Depends(require_owner)) -> dict:
    """What each item costs to make and keeps, worst margin first."""
    return margin.margin_report(caller.db)


@router.get("/reports/alerts")
def needs_you(business_date: date | None = None, caller: Caller = Depends(require_owner)) -> dict:
    """What needs the owner on a day (default today), worked out from the records."""
    return {"alerts": alerts.build(caller.db, business_date)}
