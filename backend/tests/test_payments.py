"""Online payments through Razorpay (test mode). Razorpay's HTTP is never called:
a fake client records what would have been sent."""

import hashlib
import hmac
import json

import pytest

from app.core.config import get_settings
from app.services import payments
from tests.conftest import FakeDevice, build_catalogue

API = "/api/v1"
KEY_SECRET = "test-key-secret-not-real"
HOOK_SECRET = "test-webhook-secret-not-real"


class FakeRazorpay:
    def __init__(self):
        self.orders: list[dict] = []

    def __call__(self, body: dict) -> dict:
        self.orders.append(body)
        return {"id": f"order_TEST{len(self.orders):04d}", "amount": body["amount"]}


@pytest.fixture
def rzp(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "razorpay_key_id", "rzp_test_PUBLICKEY")
    monkeypatch.setattr(s, "razorpay_key_secret", KEY_SECRET)
    monkeypatch.setattr(s, "razorpay_webhook_secret", HOOK_SECRET)
    fake = FakeRazorpay()
    payments.set_client(fake)
    yield fake
    payments.set_client(None)


@pytest.fixture
def device(client, shop_a):
    build_catalogue(client, shop_a)
    return FakeDevice(client, shop_a)


def _synced_bill(device, mode="upi", qty=2) -> dict:
    b = device.bill([("Masala tea", qty, [])], payment_mode=mode)
    assert device.sync([b]).json()["results"][0]["status"] == "accepted"
    return b


def _sign(order_id: str, payment_id: str, secret=KEY_SECRET) -> str:
    return hmac.new(
        secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()


def _hook(client, event: str, entity: dict, secret=HOOK_SECRET):
    body = json.dumps({"event": event, "payload": {"payment": {"entity": entity}}}).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        f"{API}/payments/razorpay/webhook",
        content=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )


def _order(client, h, bill, method="upi"):
    return client.post(
        f"{API}/payments/razorpay/order", json={"bill_id": bill["id"], "method": method}, headers=h
    )


def _status(client, h, order_id):
    return client.get(f"{API}/payments/razorpay/status?order_id={order_id}", headers=h)


def test_switched_off_without_keys(client, shop_a, device):
    """No keys on the server: the app offers only plain modes, the API refuses."""
    payments.set_client(FakeRazorpay())
    try:
        assert device.catalogue["shop"]["online_payments"] is False
        bill = _synced_bill(device)
        r = _order(client, shop_a.cashier_h, bill)
        assert r.status_code == 503 and r.json()["detail"] == "online_payments_off"
    finally:
        payments.set_client(None)


def test_order_is_for_the_bill_total_and_made_once(client, shop_a, device, rzp):
    device.refresh_catalogue()
    assert device.catalogue["shop"]["online_payments"] is True
    bill = _synced_bill(device)
    h = shop_a.cashier_h

    r = _order(client, h, bill)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["razorpay_order_id"] == "order_TEST0001"
    assert out["amount_paise"] == bill["totals"]["total"] == 4000
    assert out["status"] == "created"
    (sent,) = rzp.orders
    assert sent["amount"] == 4000 and sent["currency"] == "INR"
    assert sent["receipt"] == bill["invoice_no"]
    assert sent["notes"]["bill_id"] == bill["id"]

    # Asking again (a retry, or the cashier tapping twice) reuses the order.
    assert _order(client, h, bill).json()["razorpay_order_id"] == "order_TEST0001"
    assert len(rzp.orders) == 1


def test_bill_must_be_on_the_server_and_not_void(client, shop_a, device, rzp):
    unsent = device.bill([("Masala tea", 1, [])], payment_mode="upi")
    r = _order(client, shop_a.cashier_h, unsent)
    assert r.status_code == 409 and r.json()["detail"] == "bill_not_on_server"

    bill = _synced_bill(device)
    client.post(
        f"{API}/bills/{bill['id']}/void", json={"reason": "duplicate"}, headers=shop_a.owner_h
    ).raise_for_status()
    r = _order(client, shop_a.cashier_h, bill)
    assert r.status_code == 409 and r.json()["detail"] == "bill_void"
    assert rzp.orders == []


def test_checkout_page_runs_on_the_api_origin(client, shop_a, device, rzp):
    bill = _synced_bill(device)
    oid = _order(client, shop_a.cashier_h, bill).json()["razorpay_order_id"]
    r = client.get(f"{API}/payments/razorpay/checkout?order_id={oid}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    page = r.text
    assert "https://checkout.razorpay.com/v1/checkout.js" in page
    assert oid in page and "rzp_test_PUBLICKEY" in page and '"amount": 4000' in page
    assert KEY_SECRET not in page  # only the public key id ever leaves the server
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert client.get(f"{API}/payments/razorpay/checkout?order_id=order_NOPE").status_code == 404


def test_paid_only_with_a_valid_signature(client, shop_a, device, rzp):
    bill = _synced_bill(device)
    h = shop_a.cashier_h
    oid = _order(client, h, bill).json()["razorpay_order_id"]
    verify = f"{API}/payments/razorpay/verify"

    forged = {
        "razorpay_order_id": oid,
        "razorpay_payment_id": "pay_FORGED",
        "razorpay_signature": _sign(oid, "pay_FORGED", secret="guessed"),
    }
    assert client.post(verify, json=forged).status_code == 400
    assert _status(client, h, oid).json()["status"] == "created"

    good = {
        "razorpay_order_id": oid,
        "razorpay_payment_id": "pay_GOOD1",
        "razorpay_signature": _sign(oid, "pay_GOOD1"),
    }
    assert client.post(verify, json=good).json()["status"] == "paid"
    assert client.post(verify, json=good).json()["status"] == "paid"  # a retry changes nothing
    st = _status(client, h, oid).json()
    assert st == {"status": "paid", "paid_paise": 4000, "error": ""}

    r = _order(client, h, bill)
    assert r.status_code == 409 and r.json()["detail"] == "already_paid"


def test_webhook_checks_its_signature_and_is_idempotent(client, shop_a, device, rzp):
    bill = _synced_bill(device)
    h = shop_a.cashier_h
    oid = _order(client, h, bill).json()["razorpay_order_id"]
    failed = {
        "id": "pay_F1",
        "order_id": oid,
        "amount": 4000,
        "status": "failed",
        "error_description": "Payment was cancelled by the customer",
    }
    assert _hook(client, "payment.failed", failed, secret="wrong").status_code == 400
    assert _status(client, h, oid).json()["status"] == "created"

    assert _hook(client, "payment.failed", failed).status_code == 200
    st = _status(client, h, oid).json()
    assert st["status"] == "failed" and "cancelled" in st["error"]

    # The customer tries again on the same order; Razorpay captures a different amount
    # (it never should, but if it did the owner must see it).
    captured = {"id": "pay_C1", "order_id": oid, "amount": 3900, "status": "captured"}
    for _ in range(2):  # Razorpay delivers at least once
        assert _hook(client, "payment.captured", captured).status_code == 200
    assert _status(client, h, oid).json() == {"status": "paid", "paid_paise": 3900, "error": ""}
    # A late failure of an earlier attempt does not undo a payment.
    assert _hook(client, "payment.failed", failed).status_code == 200
    assert _status(client, h, oid).json()["status"] == "paid"
    # Orders this server never made are acknowledged and ignored (no retry storm).
    stray = {"id": "pay_X", "order_id": "order_OTHER", "amount": 100, "status": "captured"}
    assert _hook(client, "payment.captured", stray).status_code == 200

    rep = client.get(f"{API}/reports/sales", headers=shop_a.owner_h).json()
    (online,) = rep["online_payments"]
    assert online["invoice_no"] == bill["invoice_no"]
    assert online["method"] == "upi" and online["status"] == "paid"
    assert online["amount_paise"] == 4000 and online["paid_paise"] == 3900
    assert online["provider_payment_id"] == "pay_C1"
    assert online["problem"] == "amount_mismatch"


def test_owner_report_flags_unpaid_and_void_after_payment(client, shop_a, device, rzp):
    h = shop_a.cashier_h
    unpaid = _synced_bill(device, qty=1)
    _order(client, h, unpaid)
    paid = _synced_bill(device, mode="card")
    oid = _order(client, h, paid, method="card").json()["razorpay_order_id"]
    client.post(
        f"{API}/payments/razorpay/verify",
        json={
            "razorpay_order_id": oid,
            "razorpay_payment_id": "pay_V1",
            "razorpay_signature": _sign(oid, "pay_V1"),
        },
    ).raise_for_status()
    client.post(
        f"{API}/bills/{paid['id']}/void", json={"reason": "duplicate"}, headers=shop_a.owner_h
    ).raise_for_status()

    rep = client.get(f"{API}/reports/sales", headers=shop_a.owner_h).json()
    problems = {p["invoice_no"]: p["problem"] for p in rep["online_payments"]}
    assert problems == {unpaid["invoice_no"]: "not_paid", paid["invoice_no"]: "refund_due"}


def test_other_shops_cannot_see_or_pay_my_orders(client, shop_a, shop_b, device, rzp):
    bill = _synced_bill(device)
    oid = _order(client, shop_a.cashier_h, bill).json()["razorpay_order_id"]
    assert _status(client, shop_b.owner_h, oid).status_code == 404
    r = _order(client, shop_b.owner_h, bill)
    assert r.status_code == 409 and r.json()["detail"] == "bill_not_on_server"
    rep = client.get(f"{API}/reports/sales", headers=shop_b.owner_h).json()
    assert rep["online_payments"] == []
