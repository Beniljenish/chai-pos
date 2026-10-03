"""Online payments through Razorpay (README, "Phase 8a").

Staff (logged in):    POST /payments/razorpay/order, GET /payments/razorpay/status
Public, by signature: GET  /payments/razorpay/checkout  (the page that runs Checkout)
                      POST /payments/razorpay/verify    (Checkout's signed result)
                      POST /payments/razorpay/failed    (an attempt failed; never marks paid)
                      POST /payments/razorpay/webhook   (Razorpay's own report, signed)

Why the Checkout page lives here and not in the app: the app's security policy
allows no third-party script, because the app keeps its refresh token in the
browser. Razorpay's script runs on this page instead, on the API's address,
where nothing secret is stored; the app opens it in a new tab and watches the
payment's status on the server.
"""

import html
import json
import logging
import secrets
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Caller, get_caller, require_owner
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import Bill, Payment, Shop
from app.services import payments
from app.services.reports import rupees

log = logging.getLogger(__name__)
router = APIRouter(prefix="/payments/razorpay", tags=["payments"])


class OrderIn(BaseModel):
    bill_id: uuid.UUID
    method: Literal["upi", "card"]


class VerifyIn(BaseModel):
    razorpay_order_id: str = Field(max_length=40)
    razorpay_payment_id: str = Field(max_length=40)
    razorpay_signature: str = Field(max_length=128)


class FailedIn(BaseModel):
    razorpay_order_id: str = Field(max_length=40)
    reason: str = Field(default="", max_length=500)


def _out(p: Payment) -> dict:
    return {
        "razorpay_order_id": p.provider_order_id,
        "amount_paise": p.amount_paise,
        "method": p.method,
        "status": p.status,
    }


@router.post("/order")
def create_order(body: OrderIn, caller: Caller = Depends(get_caller)) -> dict:
    """A Razorpay order for a bill that is already on the server."""
    try:
        p = payments.create_order(caller.db, body.bill_id, body.method, caller.user.id)
    except payments.PaymentError as e:
        raise HTTPException(e.status, e.code) from None
    caller.db.commit()
    return _out(p)


@router.get("/health")
def health(caller: Caller = Depends(require_owner)) -> dict:
    """Owner: are the Razorpay keys set and accepted? (Shop & GST shows it.)"""
    return payments.health()


@router.get("/status")
def status(order_id: str = Query(max_length=40), caller: Caller = Depends(get_caller)) -> dict:
    p = caller.db.scalar(select(Payment).where(Payment.provider_order_id == order_id))
    if p is None:
        raise HTTPException(404, "Not found")
    return {"status": p.status, "paid_paise": p.paid_paise, "error": p.error}


# ---------------------------------------------------------------- public, signed
def _by_order(db, order_id: str) -> Payment | None:
    return db.scalar(select(Payment).where(Payment.provider_order_id == order_id))


@router.post("/verify")
def verify(body: VerifyIn) -> dict:
    """Checkout's success callback. Only a valid signature (made with the key
    secret, which only Razorpay and this server know) marks a bill paid."""
    if not payments.signature_ok(
        body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature
    ):
        raise HTTPException(400, "bad_signature")
    with SessionLocal() as db:
        p = _by_order(mark_system(db), body.razorpay_order_id)
        if p is None:
            raise HTTPException(404, "Not found")
        # Then ask Razorpay itself: captures an authorized payment, records the
        # amount Razorpay actually took (see services/payments.confirm).
        try:
            payments.confirm(p, body.razorpay_payment_id)
        except payments.PaymentError as e:
            db.rollback()
            raise HTTPException(e.status, e.code) from None
        db.commit()
        return {"status": p.status}


@router.post("/failed")
def failed(body: FailedIn) -> dict:
    """Checkout says an attempt failed. Unsigned, so it can only ever record a
    failure, never a payment; a later success still wins."""
    with SessionLocal() as db:
        p = _by_order(mark_system(db), body.razorpay_order_id)
        if p is None:
            raise HTTPException(404, "Not found")
        payments.mark_failed(p, body.reason)
        db.commit()
        return {"status": p.status}


@router.post("/webhook")
async def webhook(request: Request) -> dict:
    """Razorpay's server-to-server report. Covers the customer who paid and then
    closed the tab before Checkout could tell us."""
    if not get_settings().razorpay_webhook_secret.strip():
        raise HTTPException(503, "webhook_not_configured")
    body = await request.body()
    if not payments.webhook_ok(body, request.headers.get("X-Razorpay-Signature")):
        raise HTTPException(400, "bad_signature")
    event = json.loads(body)
    kind = event.get("event")
    entity = (((event.get("payload") or {}).get("payment") or {}).get("entity")) or {}
    handled = ("payment.authorized", "payment.captured", "payment.failed", "order.paid")
    if kind not in handled or not entity.get("order_id"):
        return {"ok": True, "ignored": True}
    with SessionLocal() as db:
        p = _by_order(mark_system(db), str(entity["order_id"]))
        if p is None:
            # Not ours (another app on the same Razorpay account): acknowledge, so
            # Razorpay does not keep retrying it.
            return {"ok": True, "ignored": True}
        try:
            # authorized -> captured here; captured -> paid; failed -> failed.
            payments.settle_from_razorpay(p, entity)
        except payments.PaymentError:
            # Capture failed (Razorpay busy): a non-2xx makes Razorpay send it again.
            db.rollback()
            raise HTTPException(503, "capture_failed_retry") from None
        db.commit()
    return {"ok": True}


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pay {amount_text}</title>
<style nonce="{nonce}">
body{{font-family:system-ui,sans-serif;margin:0;padding:24px 16px;background:#f3f4f6;
color:#1d2731;text-align:center}}
main{{max-width:420px;margin:0 auto;background:#fff;border-radius:16px;padding:24px 16px}}
h1{{font-size:1.2rem;margin:0 0 4px}} .amt{{font-size:2.4rem;font-weight:800;margin:12px 0}}
button{{font:inherit;font-weight:700;font-size:1.1rem;border:0;border-radius:12px;padding:14px 20px;
background:#1f6b4f;color:#fff;width:100%}} #msg{{min-height:1.5em;font-weight:700}}
.ok{{color:#1f6b4f}} .bad{{color:#b3261e}} .muted{{color:#5b6670;font-size:.9rem}}
</style></head>
<body><main>
<h1>{shop}</h1><p class="muted">Bill {invoice}</p>
<p class="amt">{amount_text}</p>
<p id="msg" role="status"></p>
<button id="pay">Pay {amount_text}</button>
<p class="muted">Test mode. When it says Paid, go back to the till.</p>
</main>
<script nonce="{nonce}" src="https://checkout.razorpay.com/v1/checkout.js"></script>
<script nonce="{nonce}">
const o = {options};
const msg = document.getElementById('msg'), btn = document.getElementById('pay');
function say(t, cls) {{ msg.textContent = t; msg.className = cls || ''; }}
function post(path, body) {{
  return fetch(path, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(body) }}).then(function (r) {{ return r.json(); }});
}}
const rzp = new Razorpay(Object.assign(o, {{
  handler: function (r) {{
    say('Checking the payment…');
    post('verify', r).then(function (x) {{
      if (x.status === 'paid') {{ say('Paid. Go back to the till.', 'ok'); btn.hidden = true; }}
      else say('Could not confirm the payment. Ask the cashier.', 'bad');
    }}, function () {{
      say('Could not reach the shop. The cashier will see it shortly.', 'bad');
    }});
  }},
  modal: {{ ondismiss: function () {{ if (!btn.hidden) say('Not paid yet.'); }} }}
}}));
rzp.on('payment.failed', function (r) {{
  const why = (r && r.error && r.error.description) || 'Payment failed';
  say(why + '. Try again, or pay another way.', 'bad');
  post('failed', {{ razorpay_order_id: o.order_id, reason: why }});
}});
btn.onclick = function () {{ rzp.open(); }};
rzp.open();
</script>
</body></html>"""


def _js(value: dict) -> str:
    """JSON that is safe inside a <script> element."""
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _only(method: str) -> dict:
    """Checkout's display config that shows one payment method and nothing else."""
    if method == "upi":
        # QR for a customer at the counter, collect (type the UPI id), or intent
        # (this phone's UPI app).
        instrument = {"method": "upi", "flows": ["qr", "collect", "intent"]}
        name = "Pay by UPI"
    else:
        instrument = {"method": "card"}
        name = "Pay by card"
    return {
        "display": {
            "blocks": {method: {"name": name, "instruments": [instrument]}},
            "sequence": [f"block.{method}"],
            "preferences": {"show_default_blocks": False},
        }
    }


@router.get("/checkout", response_class=HTMLResponse)
def checkout(order_id: str = Query(max_length=40)) -> HTMLResponse:
    """The page that runs Razorpay Checkout for one order. Public: it is opened
    in a new tab without the app's login. It shows only what the customer is
    paying for, and the public key id; the order id it needs is unguessable."""
    with SessionLocal() as db:
        mark_system(db)
        p = _by_order(db, order_id)
        if p is None or not payments.enabled():
            return HTMLResponse("<!doctype html><title>Not found</title>Not found", 404)
        bill = db.get(Bill, p.bill_id)
        shop = db.get(Shop, p.shop_id)
        if p.status == "paid":
            return HTMLResponse(
                "<!doctype html><meta name=viewport content='width=device-width'>"
                "<title>Paid</title><p>This bill is already paid.</p>"
            )
        nonce = secrets.token_urlsafe(16)
        options = {
            "key": payments.keys()[0],
            "amount": p.amount_paise,
            "currency": "INR",
            "order_id": p.provider_order_id,
            "name": shop.name,
            "description": f"Bill {bill.invoice_no}",
            "theme": {"color": "#1f6b4f"},
            # Only the method the cashier chose. (prefill.method is only a hint,
            # ignored unless the customer's phone and email are prefilled.)
            "config": _only(p.method),
        }
        page = _PAGE.format(
            nonce=nonce,
            shop=html.escape(shop.name),
            invoice=html.escape(bill.invoice_no),
            amount_text=html.escape(rupees(p.amount_paise)),
            options=_js(options),
        )
    return HTMLResponse(
        page,
        headers={
            # Razorpay's script loads its own frames and assets, so the policy here
            # only stops this page being framed or its forms being redirected.
            "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'none'",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )
