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
import logging
import uuid
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.models import Bill, BillStatus, Payment

log = logging.getLogger(__name__)

RAZORPAY_API = "https://api.razorpay.com/v1"


class PaymentError(Exception):
    """A refusal the app shows to the cashier; `code` is the API detail."""

    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


class RazorpayApi(Protocol):
    """The four Razorpay calls the shop needs. Tests use a fake; nothing else does."""

    def create_order(self, body: dict) -> dict: ...
    def fetch_payment(self, payment_id: str) -> dict: ...
    def capture(self, payment_id: str, amount: int) -> dict: ...
    def ping(self) -> None: ...


_override: RazorpayApi | None = None


def set_client(client: RazorpayApi | None) -> None:
    global _override
    _override = client


def keys() -> tuple[str, str]:
    """The key id and secret as set in Vercel, without the stray space or newline
    a paste often adds (Razorpay would refuse every call with them)."""
    s = get_settings()
    return s.razorpay_key_id.strip(), s.razorpay_key_secret.strip()


def enabled() -> bool:
    return all(keys())


class _Http:
    def __init__(self, key_id: str, secret: str):
        self.auth = (key_id, secret)

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            r = httpx.request(
                method, f"{RAZORPAY_API}{path}", json=body, auth=self.auth, timeout=10
            )
        except httpx.HTTPError as e:
            log.warning("razorpay %s %s: %s", method, path.split("/")[1], type(e).__name__)
            raise PaymentError("razorpay_unreachable", 502) from None
        if r.status_code in (401, 403):
            raise PaymentError("razorpay_keys_refused", 502)
        if r.status_code >= 400:
            # Razorpay's own words (never contain the keys); logged for the owner.
            reason = (r.json().get("error") or {}).get("description", "") if r.content else ""
            log.warning(
                "razorpay %s %s refused (%s): %s", method, path.split("/")[1], r.status_code, reason
            )
            raise PaymentError("razorpay_refused", 502)
        return r.json()

    def create_order(self, body: dict) -> dict:
        return self._call("POST", "/orders", body)

    def fetch_payment(self, payment_id: str) -> dict:
        return self._call("GET", f"/payments/{payment_id}")

    def capture(self, payment_id: str, amount: int) -> dict:
        return self._call(
            "POST", f"/payments/{payment_id}/capture", {"amount": amount, "currency": "INR"}
        )

    def ping(self) -> None:
        self._call("GET", "/orders?count=1")


def _client() -> RazorpayApi:
    return _override if _override is not None else _Http(*keys())


def _hmac(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def signature_ok(order_id: str, payment_id: str, signature: str) -> bool:
    secret = keys()[1]
    if not secret:
        return False
    expected = _hmac(secret, f"{order_id}|{payment_id}".encode())
    return hmac.compare_digest(expected, signature or "")


def webhook_ok(body: bytes, signature: str | None) -> bool:
    secret = get_settings().razorpay_webhook_secret.strip()
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
    order = _client().create_order(
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


def confirm(p: Payment, payment_id: str) -> None:
    """After Checkout's signature checked out: ask Razorpay what happened to the
    payment and settle the row on that. An 'authorized' payment is captured here,
    so a Razorpay account set to capture manually never refunds a sale days later.
    If Razorpay cannot be asked right now, the signature (which only Razorpay can
    make) is enough to show the bill paid; the webhook confirms the amount later."""
    try:
        pay = _client().fetch_payment(payment_id)
    except PaymentError as e:
        if e.code == "razorpay_refused":
            raise PaymentError("payment_not_found", 400) from None
        mark_paid(p, payment_id, p.amount_paise)  # Razorpay unreachable: trust the signature
        return
    if pay.get("order_id") != p.provider_order_id:
        raise PaymentError("payment_not_for_this_order", 400)
    settle_from_razorpay(p, pay)


def settle_from_razorpay(p: Payment, pay: dict) -> None:
    """Record a Razorpay payment entity on its row: captured -> paid; authorized
    -> captured now, then paid; failed -> failed. Paid is final, so a repeat (a
    retried verify, a second webhook) changes nothing and captures nothing."""
    if p.status == "paid":
        return
    status = pay.get("status")
    if status == "authorized":
        pay = _client().capture(pay["id"], int(pay["amount"]))
        status = pay.get("status")
    if status == "captured":
        mark_paid(p, str(pay["id"]), int(pay["amount"]))
    elif status == "failed":
        mark_failed(p, str(pay.get("error_description") or "Payment failed"))


def health() -> dict:
    """What the owner sees under Shop & GST: are the keys set, test or live, and
    does Razorpay accept them? Never returns a key."""
    key_id, secret = keys()
    out = {
        "configured": bool(key_id and secret),
        "mode": "live"
        if key_id.startswith("rzp_live_")
        else "test"
        if key_id.startswith("rzp_test_")
        else None,
        "webhook_secret": bool(get_settings().razorpay_webhook_secret.strip()),
        "reachable": False,
        "problem": None,
    }
    if not out["configured"]:
        out["problem"] = "keys_missing"
    elif not key_id.startswith("rzp_"):
        out["problem"] = "key_id_should_start_with_rzp_"
    else:
        try:
            _client().ping()
            out["reachable"] = True
        except PaymentError as e:
            out["problem"] = e.code
    return out


def problem(p: Payment, bill: Bill) -> str | None:
    """What the owner should look at, if anything."""
    if bill.status == BillStatus.void:
        return "refund_due" if p.status == "paid" else None
    if p.status != "paid":
        return "not_paid"
    if p.paid_paise != bill.total_paise:
        return "amount_mismatch"
    return None
