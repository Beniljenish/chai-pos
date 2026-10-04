"""Scheduled work, called once a day by Vercel Cron (backend/vercel.json).

Vercel sends `Authorization: Bearer $CRON_SECRET`; without a configured secret
the endpoint refuses everything, so it can never be triggered by a stranger.
Every step is idempotent (outbox dedupe keys), so a retried or doubled run
sends nothing twice.
"""

import hmac
from datetime import date, timedelta

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import select

from app.core.config import get_settings
from app.core.time import business_date, utcnow
from app.db.session import SessionLocal
from app.db.tenancy import bind_tenant, mark_system
from app.models import Shop
from app.services import email, messages, reports

router = APIRouter(tags=["ops"])


def _authorised(header: str | None) -> bool:
    secret = get_settings().cron_secret
    return bool(secret) and hmac.compare_digest(header or "", f"Bearer {secret}")


@router.get("/cron/daily")
def daily(authorization: str | None = Header(default=None), today: date | None = None) -> dict:
    """Yesterday's sales summary for every shop; on Mondays, last week's data;
    then deliver everything still waiting (retries included)."""
    if not _authorised(authorization):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not allowed")
    today = today or business_date(utcnow())
    yesterday = today - timedelta(days=1)
    week = reports.week_before(today)

    with SessionLocal() as db:
        shop_ids = list(mark_system(db).scalars(select(Shop.id)))
    queued = 0
    for shop_id in shop_ids:
        with SessionLocal() as db:
            bind_tenant(db, shop_id)
            shop = db.scalar(select(Shop))
            reports.enqueue_daily(db, shop, yesterday)
            if week:
                reports.enqueue_weekly(db, shop, *week)
            db.commit()
            queued += 1
    with SessionLocal() as db:
        stats = email.deliver_pending(mark_system(db), limit=1000)
    with SessionLocal() as db:
        stats["messages"] = messages.deliver_pending(mark_system(db), limit=1000)
    return {"shops": queued, "date": yesterday.isoformat(), "weekly": bool(week), **stats}
