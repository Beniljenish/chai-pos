"""Staff attendance and the pay sheet (README, "9.21").

A person taps clock in and clock out on the till. It is written on the server, so it needs a
connection (unlike a bill); if someone forgets, the owner corrects the entry and the correction is
recorded. Hours come only from finished entries; an entry still open is shown, never guessed.
Pay is `hours × the hourly rate the owner set`, in integer paise, rounded half up once per person
for the whole range, not per day.
"""

import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import business_date, utcnow
from app.models import Attendance, User
from app.services.online import OnlineError

MAX_SHIFT_HOURS = 18  # an entry longer than this is almost surely a forgotten clock-out


def clock_in(db: Session, user_id: uuid.UUID) -> Attendance:
    if open_entry(db, user_id) is not None:
        raise OnlineError("already_in", "You are already clocked in.", 409)
    now = utcnow()
    row = Attendance(user_id=user_id, clock_in_at=now, business_date=business_date(now))
    db.add(row)
    db.commit()
    return row


def clock_out(db: Session, user_id: uuid.UUID) -> Attendance:
    row = open_entry(db, user_id)
    if row is None:
        raise OnlineError("not_in", "You are not clocked in.", 409)
    row.clock_out_at = utcnow()
    db.commit()
    return row


def open_entry(db: Session, user_id: uuid.UUID) -> Attendance | None:
    return db.scalar(
        select(Attendance)
        .where(Attendance.user_id == user_id, Attendance.clock_out_at.is_(None))
        .order_by(Attendance.clock_in_at.desc())
        .limit(1)
    )


def minutes(row: Attendance) -> int | None:
    if row.clock_out_at is None:
        return None
    return int((row.clock_out_at - row.clock_in_at).total_seconds() // 60)


def pay_paise(total_minutes: int, rate_paise_per_hour: int | None) -> int | None:
    if not rate_paise_per_hour:
        return None
    return int(
        (Decimal(total_minutes) * rate_paise_per_hour / 60).quantize(Decimal(1), ROUND_HALF_UP)
    )


def view(row: Attendance) -> dict:
    m = minutes(row)
    return {
        "id": row.id,
        "user_id": row.user_id,
        "date": row.business_date,
        "clock_in_at": row.clock_in_at,
        "clock_out_at": row.clock_out_at,
        "minutes": m,
        "note": row.note,
        "edited": row.edited_by is not None,
        "too_long": m is not None and m > MAX_SHIFT_HOURS * 60,
    }


def report(db: Session, start: date, end: date) -> dict:
    rows = db.scalars(
        select(Attendance)
        .where(Attendance.business_date >= start, Attendance.business_date <= end)
        .order_by(Attendance.clock_in_at)
    ).all()
    people = {u.id: u for u in db.scalars(select(User))}
    by_user: dict[uuid.UUID, list[Attendance]] = {}
    for r in rows:
        by_user.setdefault(r.user_id, []).append(r)
    out = []
    for uid, entries in by_user.items():
        u = people.get(uid)
        total = sum(m for e in entries if (m := minutes(e)) is not None)
        rate = u.hourly_rate_paise if u else None
        out.append(
            {
                "user_id": uid,
                "name": u.name if u else "Unknown",
                "minutes": total,
                "still_in": any(e.clock_out_at is None for e in entries),
                "rate_paise": rate,
                "pay_paise": pay_paise(total, rate),
                "entries": [view(e) for e in entries],
            }
        )
    out.sort(key=lambda p: p["name"].lower())
    return {"from": start, "to": end, "people": out}


def correct(
    db: Session,
    row: Attendance,
    editor: uuid.UUID,
    clock_in_at: datetime | None,
    clock_out_at: datetime | None,
    note: str | None,
) -> None:
    new_in = clock_in_at or row.clock_in_at
    new_out = clock_out_at if clock_out_at is not None else row.clock_out_at
    if new_out is not None and new_out < new_in:
        raise OnlineError("bad_times", "The time out is before the time in.", 422)
    row.clock_in_at, row.clock_out_at = new_in, new_out
    row.business_date = business_date(new_in)
    if note is not None:
        row.note = note.strip()[:120]
    row.edited_by, row.edited_at = editor, utcnow()
