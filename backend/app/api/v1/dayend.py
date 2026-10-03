"""Wastage and the day-end close.

Cashiers record wastage and count; they never see expected quantities or
rupee values (blind counts). The owner sees the variance report and approves.
"""

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.api.common import get_or_404, unprocessable
from app.api.deps import Caller, get_caller, require_owner
from app.core.time import business_date as business_date_of
from app.core.time import utcnow
from app.models import (
    DayCountStatus,
    Ingredient,
    MenuItem,
    Role,
    User,
    WastageEntry,
)
from app.schemas_dayend import (
    CountsIn,
    ReportLineOut,
    ReportOut,
    SheetItem,
    SheetOut,
    SubmitOut,
    WastageIn,
    WastageOut,
)
from app.services import dayend
from app.services.stock import PackQty

router = APIRouter(tags=["day-end"])


def _day(business_date: date) -> date:
    today = business_date_of(utcnow())
    if business_date > today:
        raise unprocessable("That day has not started yet")
    if business_date < today - timedelta(days=30):
        raise unprocessable("Counts older than 30 days cannot be changed")
    return business_date


# ---------------------------------------------------------------- wastage
@router.post("/wastage", response_model=WastageOut, status_code=201)
def record_wastage(body: WastageIn, caller: Caller = Depends(get_caller)):
    ingredient = (
        get_or_404(caller.db, Ingredient, body.ingredient_id) if body.ingredient_id else None
    )
    item = get_or_404(caller.db, MenuItem, body.menu_item_id) if body.menu_item_id else None
    try:
        entry = dayend.record_wastage(
            caller.db,
            ingredient=ingredient,
            menu_item=item,
            qty=body.qty,
            reason=body.reason,
            note=body.note.strip(),
            user_id=caller.user.id,
            is_owner=caller.ctx.role == Role.owner,
        )
    except PermissionError as e:
        caller.db.rollback()
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from None
    except dayend.DayEndError as e:
        caller.db.rollback()
        raise unprocessable(str(e)) from None
    caller.db.commit()
    return _wastage_out(caller, [entry])[0]


@router.get("/wastage", response_model=list[WastageOut])
def list_wastage(business_date: date | None = None, caller: Caller = Depends(get_caller)):
    day = business_date or business_date_of(utcnow())
    entries = caller.db.scalars(
        select(WastageEntry)
        .where(WastageEntry.business_date == day)
        .order_by(WastageEntry.created_at.desc())
    ).all()
    return _wastage_out(caller, entries)


def _wastage_out(caller: Caller, entries) -> list[WastageOut]:
    owner = caller.ctx.role == Role.owner
    ing = {i.id: i for i in caller.db.scalars(select(Ingredient))}
    items = {m.id: m for m in caller.db.scalars(select(MenuItem))}
    users = dict(caller.db.execute(select(User.id, User.name)).all())
    out = []
    for e in entries:
        target = ing.get(e.ingredient_id) if e.ingredient_id else items.get(e.menu_item_id)
        out.append(
            WastageOut(
                id=e.id,
                name=target.name if target else "?",
                is_menu_item=e.menu_item_id is not None,
                qty=e.qty,
                base_unit=ing[e.ingredient_id].base_unit if e.ingredient_id else None,
                reason=e.reason,
                note=e.note,
                value_paise=e.value_paise if owner else None,
                created_by_name=users.get(e.created_by, "?"),
                created_at=e.created_at,
            )
        )
    return out


# ---------------------------------------------------------------- count
@router.get(
    "/day-counts/{business_date}/sheet", response_model=SheetOut, response_model_exclude_none=True
)
def count_sheet(business_date: date, caller: Caller = Depends(get_caller)):
    """What to count, in shelf order (by name for now). Blind for cashiers; the
    owner also sees each item's expected balance, to reconcile against."""
    day = _day(business_date)
    dc = dayend.find_day(caller.db, day)
    lines = {ln.ingredient_id: ln for ln in dc.lines}
    ingredients = caller.db.scalars(
        select(Ingredient).where(Ingredient.is_active).order_by(func.lower(Ingredient.name))
    ).all()
    expected = (
        {
            i: m.expected
            for i, m in dayend.movements(caller.db, day, {x.id for x in ingredients}).items()
        }
        if caller.ctx.role == Role.owner and ingredients
        else None
    )
    return SheetOut(
        business_date=day,
        status=dc.status,
        items=[
            SheetItem(
                ingredient_id=i.id,
                name=i.name,
                kind=i.kind,
                base_unit=i.base_unit,
                count_frequency=i.count_frequency,
                pack_units=i.pack_units,
                counted=i.id in lines,
                recount=i.id in lines
                and lines[i.id].recount_requested
                and not lines[i.id].recounted,
                expected=None if expected is None else expected.get(i.id, Decimal(0)),
            )
            for i in ingredients
        ],
    )


@router.post("/day-counts/{business_date}/counts", response_model=SubmitOut)
def submit_counts(business_date: date, body: CountsIn, caller: Caller = Depends(get_caller)):
    day = _day(business_date)
    try:
        result = dayend.submit_counts(
            caller.db,
            day,
            [
                dayend.CountIn(
                    ln.ingredient_id,
                    [PackQty(p.pack_unit_id, p.qty) for p in ln.packs],
                    ln.loose_qty,
                )
                for ln in body.lines
            ],
            caller.user.id,
            # The owner counts with the expected balance in view, so asking
            # them to recount blind would be theatre; they review the report.
            ask_recount=caller.ctx.role != Role.owner,
        )
    except dayend.DayLocked as e:
        caller.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    except dayend.DayEndError as e:
        caller.db.rollback()
        raise unprocessable(str(e)) from None
    caller.db.commit()
    return SubmitOut(status=result.status, recount=result.recount)


@router.get("/day-counts/{business_date}/report", response_model=ReportOut)
def report(business_date: date, caller: Caller = Depends(require_owner)):
    day = _day(business_date)
    dc = dayend.find_day(caller.db, day)
    lines = dayend.report_lines(caller.db, dc)
    users = dict(caller.db.execute(select(User.id, User.name)).all())
    wastage = caller.db.execute(
        select(WastageEntry.reason, func.sum(WastageEntry.value_paise))
        .where(WastageEntry.business_date == day)
        .group_by(WastageEntry.reason)
    ).all()
    late, late_paise = (
        dayend.late_bills_explained(caller.db, dc)
        if dc.status == DayCountStatus.approved
        else (0, 0)
    )
    return ReportOut(
        business_date=day,
        status=dc.status,
        submitted_by_name=users.get(dc.submitted_by),
        approved_by_name=users.get(dc.approved_by),
        lines=[
            ReportLineOut(
                ingredient_id=r.ingredient.id,
                name=r.ingredient.name,
                base_unit=r.ingredient.base_unit,
                opening=r.move.opening,
                stock_in=r.move.stock_in,
                prep_in=r.move.prep_in,
                prep_out=r.move.prep_out,
                sold=r.move.sold,
                wasted=r.move.wasted,
                other=r.move.other,
                expected=r.expected,
                counted=r.counted,
                variance=r.variance,
                variance_paise=r.variance_paise,
                cost_per_unit_paise=r.cost,
                expected_usage=r.move.expected_usage,
                actual_usage=r.actual_usage,
                adherence_pct=r.adherence_pct,
                tolerance_bp=r.ingredient.tolerance_bp,
                flagged=r.flagged,
                recounted=r.recounted,
                has_opening=r.has_opening,
            )
            for r in lines
        ],
        missing_paise=-sum(min(r.variance_paise, 0) for r in lines),
        surplus_paise=sum(max(r.variance_paise, 0) for r in lines),
        flagged_count=sum(r.flagged for r in lines),
        wastage_paise=sum(int(v or 0) for _, v in wastage),
        wastage_by_reason={r.value: int(v or 0) for r, v in wastage},
        late_bills=late,
        late_bills_explained_paise=late_paise,
    )


@router.post("/day-counts/{business_date}/approve", response_model=ReportOut)
def approve(business_date: date, caller: Caller = Depends(require_owner)):
    day = _day(business_date)
    try:
        dayend.approve(caller.db, day, caller.user.id)
    except dayend.DayLocked as e:
        caller.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    except dayend.DayEndError as e:
        caller.db.rollback()
        raise unprocessable(str(e)) from None
    caller.db.commit()
    return report(business_date, caller)
