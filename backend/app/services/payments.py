"""Online payments through Razorpay (README, "Phase 8a").

    create_order()   a Razorpay order for a bill's printed total; reused on retry
    signature_ok()   Checkout's signature: HMAC-SHA256(order_id|payment_id, key secret)
    webhook_ok()     a webhook's signature: HMAC-SHA256(raw body, webhook secret)
    mark_paid() / mark_failed()   idempotent; paid is final

Keys come from the environment only (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET,
RAZORPAY_WEBHOOK_SECRET); with no key id and secret, online payments are off.
"""

import hashlib
import hmac
import uuid
from collections.abc import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.models import Bill, BillStatus, Payment

RAZORPAY_API = "https://api.razorpay.com/v1"

# (order body) -> Razorpay's order. Tests swap it for a recorder; nothing else does.
Client = Callable[[dict], dict]
_override: Client | None = None


class PaymentError(Exception):
    """A refusal the app shows to the cashier; `code` is the API detail."""

    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


def set_client(client: Client | None) -> None:
    global _override
    _override = client


def enabled() -> bool:
    s = get_settings()
    return bool(s.razorpay_key_id and s.razorpay_key_secret)


def _client() -> Client:
    if _override is not None:
        return _override
    s = get_settings()

    def create(body: dict) -> dict:
        r = httpx.post(
            f"{RAZORPAY_API}/orders",
            json=body,
            auth=(s.razorpay_key_id, s.razorpay_key_secret),
            timeout=10,
        )
        if r.status_code >= 400:
            raise PaymentError("razorpay_refused", 502)
        return r.json()

    return create


def _hmac(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def signature_ok(order_id: str, payment_id: str, signature: str) -> bool:
    secret = get_settings().razorpay_key_secret
    if not secret:
        return False
    expected = _hmac(secret, f"{order_id}|{payment_id}".encode())
    return hmac.compare_digest(expected, signature or "")


def webhook_ok(body: bytes, signature: str | None) -> bool:
    secret = get_settings().razorpay_webhook_secret
    return bool(secret) and hmac.compare_digest(_hmac(secret, body), signature or "")


def create_order(db: Session, bill_id: uuid.UUID, method: str, user_id: uuid.UUID) -> Payment:
    if not enabled():
        raise PaymentError("online_payments_off", 503)
    # Tenant-scoped: another shop's bill is simply not found.
    bill = db.scalar(select(Bill).where(Bill.id == bill_id))
    if bill is None:
        raise PaymentError("bill_not_on_server")  # the app sends it first, then asks again
    if bill.status == BillStatus.void:
        raise PaymentError("bill_void")
    if bill.total_paise <= 0:
        raise PaymentError("nothing_to_pay")
    rows = db.scalars(
        select(Payment).where(Payment.bill_id == bill.id).order_by(Payment.created_at.desc())
    ).all()
    if any(p.status == "paid" for p in rows):
        raise PaymentError("already_paid")
    for p in rows:
        # A retry (or a second tap) reuses the order: the customer can try again
        # on it after a failure, and Razorpay accepts only one success per order.
        if p.method == method and p.amount_paise == bill.total_paise:
            return p
    order = _client()(
        {
            "amount": bill.total_paise,  # paise, like ours
            "currency": "INR",
            "receipt": bill.invoice_no[:40],
            "notes": {"bill_id": str(bill.id), "invoice_no": bill.invoice_no},
        }
    )
    p = Payment(
        bill_id=bill.id,
        method=method,
        status="created",
        amount_paise=bill.total_paise,
        provider_order_id=str(order["id"]),
        error="",
        created_by=user_id,
    )
    db.add(p)
    db.flush()
    return p


def mark_paid(p: Payment, payment_id: str, paid_paise: int) -> None:
    if p.status == "paid":
        return  # a second delivery of the same news
    p.status = "paid"
    p.provider_payment_id = payment_id
    p.paid_paise = paid_paise
    p.error = ""
    p.paid_at = utcnow()


def mark_failed(p: Payment, reason: str) -> None:
    if p.status == "paid":
        return  # an earlier attempt's failure arriving late
    p.status = "failed"
    p.error = (reason or "Payment failed")[:200]


def problem(p: Payment, bill: Bill) -> str | None:
    """What the owner should look at, if anything."""
    if bill.status == BillStatus.void:
        return "refund_due" if p.status == "paid" else None
    if p.status != "paid":
        return "not_paid"
    if p.paid_paise != bill.total_paise:
        return "amount_mismatch"
    return None
