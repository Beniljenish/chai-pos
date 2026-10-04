"""Online payments through Razorpay (test mode). Razorpay's HTTP is never called:
a fake Razorpay keeps orders and payments in memory and records every call."""

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
    """Razorpay's orders and payments, as its API answers them."""

    def __init__(self):
        self.orders: list[dict] = []
        self.payments: dict[str, dict] = {}
        self.captured: list[tuple[str, int]] = []
        self.down = False  # Razorpay unreachable

    def _check(self):
        if self.down:
            raise payments.PaymentError("razorpay_unreachable", 502)

    def create_order(self, body: dict) -> dict:
        self._check()
        self.orders.append(body)
        return {"id": f"order_TEST{len(self.orders):04d}", "amount": body["amount"]}

    def pay(self, order_id: str, payment_id: str, amount: int, status="captured", method="upi"):
        """The customer paid in Checkout (Razorpay's side of it)."""
        self.payments[payment_id] = {
            "id": payment_id,
            "order_id": order_id,
            "amount": amount,
            "currency": "INR",
            "status": status,
            "method": method,
        }

    def fetch_payment(self, payment_id: str) -> dict:
        self._check()
        if payment_id not in self.payments:
            raise payments.PaymentError("razorpay_refused", 502)
        return self.payments[payment_id]

    def capture(self, payment_id: str, amount: int) -> dict:
        self._check()
        self.captured.append((payment_id, amount))
        self.payments[payment_id]["status"] = "captured"
        return self.payments[payment_id]

    def ping(self) -> None:
        self._check()


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

    rzp.pay(oid, "pay_GOOD1", 4000)
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
    rzp.pay(oid, "pay_V1", paid["totals"]["total"], method="card")
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


# ---------------------------------------------------------------- confirmed with Razorpay
def _verify(client, oid, pid):
    return client.post(
        f"{API}/payments/razorpay/verify",
        json={
            "razorpay_order_id": oid,
            "razorpay_payment_id": pid,
            "razorpay_signature": _sign(oid, pid),
        },
    )


def test_an_authorized_payment_is_captured_for_the_amount_razorpay_reports(
    client, shop_a, device, rzp
):
    """An account set to capture manually leaves a payment 'authorized', and
    Razorpay refunds it after a few days. The server captures it itself."""
    bill = _synced_bill(device)
    oid = _order(client, shop_a.cashier_h, bill).json()["razorpay_order_id"]
    rzp.pay(oid, "pay_AUTH", 4000, status="authorized")
    assert _verify(client, oid, "pay_AUTH").json()["status"] == "paid"
    assert rzp.captured == [("pay_AUTH", 4000)]
    st = _status(client, shop_a.cashier_h, oid).json()
    assert st == {"status": "paid", "paid_paise": 4000, "error": ""}
    # Verified again (a retry): nothing is captured twice.
    _verify(client, oid, "pay_AUTH")
    assert rzp.captured == [("pay_AUTH", 4000)]


def test_a_signed_payment_of_another_order_is_refused(client, shop_a, device, rzp):
    bill = _synced_bill(device)
    oid = _order(client, shop_a.cashier_h, bill).json()["razorpay_order_id"]
    rzp.pay("order_SOMEONE_ELSE", "pay_X", 100)
    r = _verify(client, oid, "pay_X")  # signed for this order, but Razorpay says otherwise
    assert r.status_code == 400 and r.json()["detail"] == "payment_not_for_this_order"
    assert _status(client, shop_a.cashier_h, oid).json()["status"] == "created"


def test_a_failed_payment_is_recorded_as_failed(client, shop_a, device, rzp):
    bill = _synced_bill(device)
    oid = _order(client, shop_a.cashier_h, bill).json()["razorpay_order_id"]
    rzp.pay(oid, "pay_F", 4000, status="failed")
    assert _verify(client, oid, "pay_F").json()["status"] == "failed"


def test_razorpay_unreachable_after_payment_still_records_the_signed_payment(
    client, shop_a, device, rzp
):
    """The signature proves Razorpay accepted the payment; if Razorpay cannot be
    asked right then, the bill is still shown paid and the webhook confirms later."""
    bill = _synced_bill(device)
    oid = _order(client, shop_a.cashier_h, bill).json()["razorpay_order_id"]
    rzp.pay(oid, "pay_D", 4000)
    rzp.down = True
    assert _verify(client, oid, "pay_D").json()["status"] == "paid"
    st = _status(client, shop_a.cashier_h, oid).json()
    assert st["status"] == "paid" and st["paid_paise"] == 4000
    # Razorpay down when asked for an order: the cashier is told, nothing half-made.
    other = _synced_bill(device, qty=1)
    r = _order(client, shop_a.cashier_h, other)
    assert r.status_code == 502 and r.json()["detail"] == "razorpay_unreachable"


def test_webhook_authorized_payment_is_captured(client, shop_a, device, rzp):
    bill = _synced_bill(device)
    oid = _order(client, shop_a.cashier_h, bill).json()["razorpay_order_id"]
    rzp.pay(oid, "pay_W", 4000, status="authorized")
    entity = {"id": "pay_W", "order_id": oid, "amount": 4000, "status": "authorized"}
    assert _hook(client, "payment.authorized", entity).status_code == 200
    assert rzp.captured == [("pay_W", 4000)]
    assert _status(client, shop_a.cashier_h, oid).json()["status"] == "paid"


@pytest.mark.parametrize("method", ["upi", "card"])
def test_checkout_shows_only_the_chosen_method(client, shop_a, device, rzp, method):
    bill = _synced_bill(device)
    oid = _order(client, shop_a.cashier_h, bill, method=method).json()["razorpay_order_id"]
    page = client.get(f"{API}/payments/razorpay/checkout?order_id={oid}").text
    start = page.index("const o = ") + len("const o = ")
    options = json.loads(page[start : page.index(";\n", start)])
    display = options["config"]["display"]
    assert display["preferences"] == {"show_default_blocks": False}
    (block,) = display["blocks"].values()
    assert [i["method"] for i in block["instruments"]] == [method]
    assert display["sequence"] == [f"block.{method}"]
    if method == "upi":  # QR on the counter tablet, collect, or the phone's UPI app
        assert block["instruments"][0]["flows"] == ["qr", "collect", "intent"]


def test_owner_can_check_the_razorpay_connection(client, shop_a, rzp, monkeypatch):
    h = shop_a.owner_h
    assert (
        client.get(f"{API}/payments/razorpay/health", headers=shop_a.cashier_h).status_code == 403
    )
    assert client.get(f"{API}/payments/razorpay/health", headers=h).json() == {
        "configured": True,
        "mode": "test",
        "webhook_secret": True,
        "reachable": True,
        "problem": None,
    }
    rzp.down = True
    r = client.get(f"{API}/payments/razorpay/health", headers=h).json()
    assert r["reachable"] is False and r["problem"] == "razorpay_unreachable"
    rzp.down = False
    # A key pasted with a space or a newline still works (stripped)...
    monkeypatch.setattr(get_settings(), "razorpay_key_id", "  rzp_test_PUBLICKEY\n")
    assert client.get(f"{API}/payments/razorpay/health", headers=h).json()["problem"] is None
    # ...but the key secret in the key id's place is named, not just "failed".
    monkeypatch.setattr(get_settings(), "razorpay_key_id", "abcdef123456")
    assert client.get(f"{API}/payments/razorpay/health", headers=h).json()["problem"] == (
        "key_id_should_start_with_rzp_"
    )


def test_keys_are_used_without_stray_whitespace(client, shop_a, device, rzp, monkeypatch):
    monkeypatch.setattr(get_settings(), "razorpay_key_id", " rzp_test_PUBLICKEY \n")
    monkeypatch.setattr(get_settings(), "razorpay_key_secret", KEY_SECRET + "\n")
    bill = _synced_bill(device)
    oid = _order(client, shop_a.cashier_h, bill).json()["razorpay_order_id"]
    page = client.get(f"{API}/payments/razorpay/checkout?order_id={oid}").text
    assert '"key": "rzp_test_PUBLICKEY"' in page
    rzp.pay(oid, "pay_S", 4000)
    assert _verify(client, oid, "pay_S").json()["status"] == "paid"  # secret stripped too
