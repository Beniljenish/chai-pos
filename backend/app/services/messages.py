"""Customer messages through an outbox (README, "Phase 8b").

    order_changed()   after an order's events: "your order is ready" for takeaway
    bill_accepted()   after a settled order's invoice arrives: the receipt link
    deliver_pending() sends what is waiting; never raises into the caller
    receipt_token() / bill_for_token()   the signed receipt link

Only customers who agreed, for that number, are messaged (`message_ok` on the
order). The phone number is read from the order when sending and is never
written to the outbox, to logs, or into an error message.

The provider is behind a Transport (to, text, idempotency key) -> provider id:
Inkbox's iMessage API when INKBOX_API_KEY is set; otherwise nothing is sent and
the row is marked "logged" so the owner can read it on the Messages screen.
"""

import hashlib
import hmac
import logging
import re
import uuid
from collections.abc import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.models import Bill, Message, Order, OrderType, Shop

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
INKBOX_URL = "https://inkbox.ai/api/v1/imessage/messages"


class SendError(Exception):
    """The provider refused or could not be reached."""


# (to in E.164, text, idempotency key) -> the provider's message id
Transport = Callable[[str, str, str], str]
_override: Transport | None = None


def set_transport(transport: Transport | None) -> None:
    """Tests (and only tests) swap the transport for a recorder."""
    global _override
    _override = transport


def _transport() -> Transport | None:
    if _override is not None:
        return _override
    s = get_settings()
    return _inkbox(s.inkbox_api_key, s.inkbox_identity_id) if s.inkbox_api_key else None


def _inkbox(api_key: str, identity_id: str) -> Transport:
    def send(to: str, text: str, key: str) -> str:
        try:
            r = httpx.post(
                INKBOX_URL,
                json={"to": to, "text": text},
                params={"agent_identity_id": identity_id} if identity_id else None,
                headers={
                    "X-API-Key": api_key,
                    "Idempotency-Key": key,
                    "Prefer": "idempotency-replay",
                },
                timeout=8,
            )
        except httpx.HTTPError as e:
            raise SendError(f"Inkbox not reachable ({type(e).__name__})") from None
        if r.status_code >= 400:
            raise SendError(f"Inkbox {r.status_code}: {r.text[:200]}")
        return str((r.json().get("message") or {}).get("id", ""))

    return send


def _scrub(error: str) -> str:
    """Errors are stored and shown to the owner: never with a phone number in them."""
    return re.sub(r"\+?\d[\d\s-]{8,}\d", "[number]", error)[:300]


def mask(phone: str) -> str:
    return "••••••" + phone[-4:] if phone else ""


# ---------------------------------------------------------------- the receipt link
def _sig(bill_id: uuid.UUID) -> str:
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, b"receipt:" + bill_id.bytes, hashlib.sha256).hexdigest()[:32]


def receipt_token(bill_id: uuid.UUID) -> str:
    return bill_id.hex + _sig(bill_id)


def bill_for_token(token: str) -> uuid.UUID | None:
    if not re.fullmatch(r"[0-9a-f]{64}", token or ""):
        return None
    bill_id = uuid.UUID(token[:32])
    return bill_id if hmac.compare_digest(_sig(bill_id), token[32:]) else None


def receipt_link(bill_id: uuid.UUID) -> str:
    return f"{get_settings().public_api_url.rstrip('/')}/receipt?t={receipt_token(bill_id)}"


# ---------------------------------------------------------------- enqueue
def _consented(order: Order) -> bool:
    s = order.state or {}
    return bool(s.get("message_ok")) and bool(s.get("customer_phone"))


def _enqueue(
    db: Session, order: Order, kind: str, key: str, text: str, bill_id=None
) -> Message | None:
    if db.scalar(select(Message.id).where(Message.dedupe_key == key)) is not None:
        return None
    sp = db.begin_nested()
    try:
        m = Message(
            order_id=order.id,
            bill_id=bill_id,
            kind=kind,
            dedupe_key=key,
            text=text,
            status="pending",
            attempts=0,
            last_error="",
            provider_id="",
        )
        db.add(m)
        db.flush()
        sp.commit()
        return m
    except IntegrityError:  # another request queued it first
        sp.rollback()
        return None


def _hello(order: Order) -> str:
    name = (order.state or {}).get("customer_name", "").strip()
    return f"Hi {name}," if name else "Hi,"


def order_changed(db: Session, order: Order) -> None:
    """Takeaway: once everything left on the order is ready, tell the customer."""
    if order.order_type != OrderType.takeaway or not _consented(order):
        return
    lines = [ln for ln in order.state.get("lines", []) if ln.get("qty", 0) > 0]
    if not lines or not all(ln.get("ready") for ln in lines):
        return
    shop = db.scalar(select(Shop))
    _enqueue(
        db,
        order,
        "ready",
        f"ready:{order.id}",
        f"{_hello(order)} your order at {shop.name} is ready. Please collect it at the counter.",
    )


def bill_accepted(db: Session, shop: Shop, bill: Bill) -> None:
    """A settled order's invoice reached the server: send the receipt link."""
    if bill.order_id is None:
        return
    order = db.scalar(select(Order).where(Order.id == bill.order_id))
    if order is None or not _consented(order):
        return
    from app.services.reports import rupees  # local: reports imports billing

    _enqueue(
        db,
        order,
        "receipt",
        f"receipt:{bill.id}",
        f"Thank you for visiting {shop.name}. Your bill {bill.invoice_no} for "
        f"{rupees(bill.total_paise)}: {receipt_link(bill.id)}",
        bill_id=bill.id,
    )


# ---------------------------------------------------------------- deliver
def deliver_pending(db: Session, limit: int = 50) -> dict:
    """Send what is waiting. Safe anywhere, any time; never raises."""
    stats = {"sent": 0, "logged": 0, "failed": 0, "retry": 0}
    try:
        transport = _transport()
        rows = db.scalars(
            select(Message).where(Message.status == "pending").order_by(Message.created_at)
        ).all()[:limit]
        for m in rows:
            order = db.get(Order, m.order_id)
            phone = (order.state or {}).get("customer_phone", "") if order else ""
            if order is None or not _consented(order):
                m.status, m.last_error = "failed", "No consent for this number"
                stats["failed"] += 1
                continue
            if transport is None:
                m.status = "logged"
                stats["logged"] += 1
                continue
            m.attempts += 1
            try:
                key = f"chai-pos:{m.shop_id}:{m.dedupe_key}"
                m.provider_id = transport(f"+91{phone}", m.text, key)[:100]
                m.status, m.sent_at, m.last_error = "sent", utcnow(), ""
                stats["sent"] += 1
            except Exception as e:  # noqa: BLE001  any provider failure is retried later
                m.last_error = _scrub(str(e) or type(e).__name__)
                if m.attempts >= MAX_ATTEMPTS:
                    m.status = "failed"
                    stats["failed"] += 1
                else:
                    stats["retry"] += 1
        db.commit()
    except Exception:  # noqa: BLE001
        log.exception("message delivery failed")  # no numbers: rows are not logged
        db.rollback()
    return stats
