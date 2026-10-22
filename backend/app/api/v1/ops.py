"""Owner tools added in README "9.21": the change log, staff attendance and pay, what was paid
for each ingredient, and special days."""

import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.common import get_or_404, unprocessable
from app.api.deps import Caller, get_caller, require_owner
from app.core.time import business_date, utcnow
from app.models import Attendance, Ingredient, SpecialDay
from app.services import attendance, audit, prices, specialdays
from app.services.online import OnlineError

router = APIRouter(tags=["owner tools"])
MAX_DAYS = 92


def _fail(e: OnlineError) -> HTTPException:
    return HTTPException(e.status, {"code": e.code, "message": e.message})


def _range(start: date | None, end: date | None) -> tuple[date, date]:
    end = end or business_date(utcnow())
    start = start or end - timedelta(days=6)
    if end < start or (end - start).days >= MAX_DAYS:
        raise unprocessable("Pick a range of up to 92 days")
    return start, end


# ---------------------------------------------------------------- the change log
@router.get("/audit")
def change_log(
    days: int = Query(default=30, ge=1, le=365), caller: Caller = Depends(require_owner)
) -> dict:
    return {"events": audit.recent(caller.db, days)}


# ---------------------------------------------------------------- attendance
@router.get("/attendance/me")
def my_attendance(caller: Caller = Depends(get_caller)) -> dict:
    row = attendance.open_entry(caller.db, caller.user.id)
    return {"open": attendance.view(row) if row else None}


@router.post("/attendance/in", status_code=201)
def clock_in(caller: Caller = Depends(get_caller)) -> dict:
    try:
        return {"open": attendance.view(attendance.clock_in(caller.db, caller.user.id))}
    except OnlineError as e:
        caller.db.rollback()
        raise _fail(e) from None


@router.post("/attendance/out")
def clock_out(caller: Caller = Depends(get_caller)) -> dict:
    try:
        attendance.clock_out(caller.db, caller.user.id)
    except OnlineError as e:
        caller.db.rollback()
        raise _fail(e) from None
    return {"open": None}


@router.get("/attendance")
def attendance_report(
    start: date | None = Query(default=None, alias="from"),
    end: date | None = Query(default=None, alias="to"),
    caller: Caller = Depends(require_owner),
) -> dict:
    s, e = _range(start, end)
    return attendance.report(caller.db, s, e)


class CorrectionIn(BaseModel):
    clock_in_at: datetime | None = None
    clock_out_at: datetime | None = None
    note: str | None = Field(default=None, max_length=120)


@router.patch("/attendance/{entry_id}")
def correct_attendance(
    entry_id: uuid.UUID, body: CorrectionIn, caller: Caller = Depends(require_owner)
) -> dict:
    row = get_or_404(caller.db, Attendance, entry_id)
    before = attendance.view(row)
    try:
        attendance.correct(
            caller.db, row, caller.user.id, body.clock_in_at, body.clock_out_at, body.note
        )
    except OnlineError as e:
        caller.db.rollback()
        raise _fail(e) from None
    audit.record(
        caller.db,
        caller.user.id,
        "attendance_corrected",
        str(row.user_id),
        before_minutes=before["minutes"],
        after_minutes=attendance.minutes(row),
    )
    caller.db.commit()
    return attendance.view(row)


# ---------------------------------------------------------------- what was paid
@router.get("/stock/prices")
def price_summary(caller: Caller = Depends(require_owner)) -> dict:
    return {"items": prices.summary(caller.db)}


@router.get("/stock/{ingredient_id}/prices")
def price_history(ingredient_id: uuid.UUID, caller: Caller = Depends(require_owner)) -> dict:
    return prices.history(caller.db, get_or_404(caller.db, Ingredient, ingredient_id))


# ---------------------------------------------------------------- special days
class SpecialDayIn(BaseModel):
    day: date
    name: str = Field(min_length=1, max_length=60)


@router.get("/special-days")
def list_special_days(caller: Caller = Depends(require_owner)) -> dict:
    return specialdays.upcoming(caller.db, business_date(utcnow()))


@router.post("/special-days", status_code=201)
def add_special_day(body: SpecialDayIn, caller: Caller = Depends(require_owner)) -> dict:
    name = body.name.strip()
    from sqlalchemy import select

    exists = caller.db.scalar(
        select(SpecialDay.id).where(SpecialDay.day == body.day, SpecialDay.name == name)
    )
    if exists is None:
        caller.db.add(SpecialDay(day=body.day, name=name))
        caller.db.commit()
    return specialdays.upcoming(caller.db, business_date(utcnow()))


@router.delete("/special-days/{special_day_id}")
def delete_special_day(special_day_id: uuid.UUID, caller: Caller = Depends(require_owner)) -> dict:
    caller.db.delete(get_or_404(caller.db, SpecialDay, special_day_id))
    caller.db.commit()
    return specialdays.upcoming(caller.db, business_date(utcnow()))
