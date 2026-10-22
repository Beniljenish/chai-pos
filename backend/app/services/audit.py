"""The change log (README, "9.21"): who changed something that matters, and what it was.

Written in the same transaction as the change, so there is never a change without its line or a
line without its change. The table is append-only (a database trigger refuses updates and
deletes). It records money-and-trust changes only: prices and GST, recipes, offers, people and the
shop's GST settings; the rest of the app already keeps its own history (bills, the stock ledger,
order events, voids).
"""

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models import AuditEvent, User


def record(db: Session, user_id: uuid.UUID | None, action: str, subject: str, **detail) -> None:
    """Add one line to the log (the caller commits). Values must be plain JSON."""
    db.add(AuditEvent(user_id=user_id, action=action, subject=subject[:120], detail=detail))


def recent(db: Session, days: int = 30, limit: int = 300) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    rows = db.scalars(
        select(AuditEvent).where(AuditEvent.at >= since).order_by(AuditEvent.at.desc()).limit(limit)
    ).all()
    names = dict(db.execute(select(User.id, User.name)).all())
    return [
        {
            "id": r.id,
            "at": r.at,
            "who": names.get(r.user_id, "Someone"),
            "action": r.action,
            "subject": r.subject,
            "detail": r.detail,
        }
        for r in rows
    ]
