"""The app's own error log (README, "9.28"): server crashes and errors from people's apps, in
one table the platform admin reads. No outside service or account needed.

Everything is scrubbed before it is written: long digit runs (phone numbers, cards) become
"[number]" and anything after "password"/"token"/"secret" is dropped. Writing never raises:
a broken error log must not turn into a second error.
"""

import logging
import re
import traceback
import uuid
from datetime import timedelta

from sqlalchemy import delete, select

from app.core.time import utcnow
from app.models import AppError

log = logging.getLogger(__name__)
KEEP_DAYS = 30
_DIGITS = re.compile(r"\+?\d[\d\s-]{7,}\d")
_SECRET = re.compile(
    r"(?i)(password|passwd|token|secret|authorization|api[_-]?key)\S*\s*[:=]?\s*\S+"
)


def scrub(text: str, limit: int) -> str:
    text = _SECRET.sub(r"\1=[hidden]", text or "")
    return _DIGITS.sub("[number]", text)[:limit]


def record(
    source: str,
    message: str,
    *,
    place: str = "",
    detail: str = "",
    agent: str = "",
    shop_id: uuid.UUID | None = None,
) -> None:
    from app.services.online import system_session

    try:
        with system_session() as db:
            db.add(
                AppError(
                    source=source,
                    shop_id=shop_id,
                    place=scrub(place, 200),
                    message=scrub(message, 500) or "(no message)",
                    detail=scrub(detail, 4000),
                    agent=scrub(agent, 200),
                )
            )
            db.commit()
    except Exception:  # noqa: BLE001  the log itself failing is only logged
        log.exception("could not write to the error log")


def record_exception(exc: BaseException, place: str) -> None:
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-4000:]
    record("server", f"{type(exc).__name__}: {exc}", place=place, detail=detail)


def recent(db, limit: int = 100) -> list[dict]:
    rows = db.scalars(select(AppError).order_by(AppError.at.desc()).limit(limit)).all()
    return [
        {
            "id": e.id,
            "at": e.at.isoformat(),
            "source": e.source,
            "place": e.place,
            "message": e.message,
            "detail": e.detail,
            "agent": e.agent,
        }
        for e in rows
    ]


def sweep(db) -> int:
    """Drop what is older than KEEP_DAYS (the daily job). The caller commits."""
    return db.execute(
        delete(AppError).where(AppError.at < utcnow() - timedelta(days=KEEP_DAYS))
    ).rowcount
