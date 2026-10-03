"""Email delivery through an outbox (see app/models/email.py).

    enqueue()          in the same transaction as the event; idempotent by key
    deliver_pending()  sends what is waiting; safe to call anywhere, any time

Delivery never raises into the caller's request: billing must not fail because
an email provider is slow. Undelivered rows are retried (by the next sync, the
next approval, or the daily cron) up to MAX_ATTEMPTS, then marked failed.
"""

import base64
import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.models import EmailKind, EmailOutbox, EmailStatus, Shop

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RESEND_URL = "https://api.resend.com"
BATCH_SIZE = 100  # Resend's batch limit; batches cannot carry attachments


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    html: str
    text: str
    attachments: Sequence[dict] = ()  # [{"filename": ..., "content": base64}]


# (messages, idempotency key) -> provider ids, one per message
Transport = Callable[[list[Message], str], list[str]]
_override: Transport | None = None


def set_transport(transport: Transport | None) -> None:
    """Tests (and only tests) swap the transport for a recorder."""
    global _override
    _override = transport


def _transport() -> Transport | None:
    if _override is not None:
        return _override
    key = get_settings().resend_api_key
    return _resend(key) if key else None


def _resend(api_key: str) -> Transport:
    def send(messages: list[Message], idempotency_key: str) -> list[str]:
        sender = get_settings().email_from

        def body(m: Message) -> dict:
            out = {
                "from": sender,
                "to": [m.to],
                "subject": m.subject,
                "html": m.html,
                "text": m.text,
            }
            if m.attachments:
                out["attachments"] = list(m.attachments)
            return out

        headers = {"Authorization": f"Bearer {api_key}", "Idempotency-Key": idempotency_key}
        if len(messages) == 1:
            r = httpx.post(
                f"{RESEND_URL}/emails", json=body(messages[0]), headers=headers, timeout=8
            )
            r.raise_for_status()
            return [r.json().get("id", "")]
        r = httpx.post(
            f"{RESEND_URL}/emails/batch",
            json=[body(m) for m in messages],
            headers=headers,
            timeout=8,
        )
        r.raise_for_status()
        return [d.get("id", "") for d in r.json().get("data", [])]

    return send


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ---------------------------------------------------------------- enqueue
def enqueue(
    db: Session,
    shop: Shop,
    kind: EmailKind,
    dedupe_key: str,
    subject: str,
    html: str,
    text: str,
    attachments: Sequence[dict] = (),
) -> EmailOutbox | None:
    """Queue one email to the shop's report address. Returns None when the shop
    has no address or the same email is already queued (same dedupe key)."""
    if not shop.report_email:
        return None
    if db.scalar(select(EmailOutbox.id).where(EmailOutbox.dedupe_key == dedupe_key)):
        return None
    row = EmailOutbox(
        kind=kind,
        dedupe_key=dedupe_key,
        to_email=shop.report_email,
        subject=subject[:200],
        html=html,
        text=text,
        attachments=list(attachments),
        status=EmailStatus.pending,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:  # enqueued by a concurrent request a moment ago
        return None
    return row


# ---------------------------------------------------------------- deliver
def deliver_pending(db: Session, *, limit: int = 300) -> dict[str, int]:
    """Send waiting emails visible to this session (one shop, or all shops in a
    system session). Commits its own progress. Never raises."""
    stats = {"sent": 0, "failed": 0, "waiting": 0}
    try:
        rows = db.scalars(
            select(EmailOutbox)
            .where(EmailOutbox.status == EmailStatus.pending)
            .order_by(EmailOutbox.created_at)
            .limit(limit)
        ).all()
        if not rows:
            return stats
        send = _transport()
        if send is None:
            stats["waiting"] = len(rows)
            log.warning("email: %d waiting, RESEND_API_KEY not set", len(rows))
            return stats
        for group in _groups(rows):
            _deliver_group(db, send, group, stats)
            db.commit()
    except Exception:  # noqa: BLE001 - delivery must never break the caller
        log.exception("email: delivery run failed")
        db.rollback()
    return stats


def _groups(rows: list[EmailOutbox]) -> list[list[EmailOutbox]]:
    bills = [r for r in rows if r.kind == EmailKind.bill and not r.attachments]
    others = [[r] for r in rows if r not in bills]
    return [bills[i : i + BATCH_SIZE] for i in range(0, len(bills), BATCH_SIZE)] + others


def _deliver_group(db: Session, send: Transport, group: list[EmailOutbox], stats) -> None:
    keys = "|".join(r.dedupe_key for r in group)
    idem = (
        group[0].dedupe_key
        if len(group) == 1
        else "batch:" + hashlib.sha256(keys.encode()).hexdigest()
    )
    messages = [Message(r.to_email, r.subject, r.html, r.text, r.attachments or ()) for r in group]
    try:
        ids = send(messages, idem)
    except Exception as e:  # noqa: BLE001 - recorded on the rows and retried
        for r in group:
            r.attempts += 1
            r.last_error = f"{type(e).__name__}: {e}"[:500]
            if r.attempts >= MAX_ATTEMPTS:
                r.status = EmailStatus.failed
                stats["failed"] += 1
        log.warning("email: send failed for %d message(s): %s", len(group), e)
        return
    now = utcnow()
    for r, provider_id in zip(group, ids + [""] * (len(group) - len(ids)), strict=False):
        r.status, r.sent_at, r.provider_id = EmailStatus.sent, now, provider_id or ""
        r.attempts += 1
        stats["sent"] += 1
