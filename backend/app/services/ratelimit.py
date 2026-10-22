"""Counting events against a limit (README, "9.17"): sign-ups from one address, codes sent to one
number. One table (`rate_hits`) and one rule: more than `limit` hits for a key in the last
`window` is refused. Old rows are swept as a side effect, so there is no job to run."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import RateHit

SWEEP_AFTER = timedelta(days=2)


class RateLimited(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def used(db: Session, key: str, window: timedelta) -> int:
    since = datetime.now(UTC) - window
    return (
        db.scalar(select(func.count(RateHit.id)).where(RateHit.key == key, RateHit.at >= since))
        or 0
    )


def hit(db: Session, key: str, *, limit: int, window: timedelta, message: str) -> None:
    """Count one event, or raise RateLimited at the limit. The caller commits."""
    if used(db, key, window) >= limit:
        raise RateLimited(message)
    db.add(RateHit(key=key))
    db.execute(delete(RateHit).where(RateHit.at < datetime.now(UTC) - SWEEP_AFTER))
    db.flush()
