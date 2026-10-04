"""Customer messages (receipt link, "order ready") by iMessage through Inkbox.
Inkbox is never called: a fake transport records what would have been sent."""

import uuid

import pytest
from sqlalchemy import inspect

from app.core.config import get_settings
from app.db.session import engine
from app.services import messages
from tests.conftest import FakeDevice, build_catalogue
from tests.test_orders import _ev, _line, _sync

API = "/api/v1"
PHONE = "9876543210"


@pytest.fixture
def setup(client, shop_a):
    """The same floor as test_orders: a catalogue, a hall with T1 and T2, a device."""
    cat = build_catalogue(client, shop_a)
    h = shop_a.owner_h
    hall = client.post(f"{API}/areas", json={"name": "Hall"}, headers=h).json()
    t1 = client.post(f"{API}/tables", json={"area_id": hall["id"], "name": "T1"}, headers=h).json()
    t2 = client.post(f"{API}/tables", json={"area_id": hall["id"], "name": "T2"}, headers=h).json()
    return cat, FakeDevice(client, shop_a), t1, t2


class FakeInkbox:
    def __init__(self, fail_with: Exception | None = None):
        self.sent: list[dict] = []
        self.fail_with = fail_with

    def __call__(self, to: str, text: str, key: str) -> str:
        if self.fail_with:
            raise self.fail_with
        self.sent.append({"to": to, "text": text, "key": key})
        return f"msg_{len(self.sent)}"


@pytest.fixture
def logging_only():
    """No Inkbox key: messages are written to the outbox and marked logged."""
    messages.set_transport(None)
    yield


@pytest.fixture
def inkbox(monkeypatch):
    monkeypatch.setattr(get_settings(), "inkbox_api_key", "test-not-a-real-key")
    fake = FakeInkbox()
    messages.set_transport(fake)
    yield fake
    messages.set_transport(None)


def _takeaway(client, h, device_id, cat, *, consent=True, phone=PHONE):
    oid, line = str(uuid.uuid4()), _line(cat, 2)
    data = {"order_type": "takeaway", "customer_name": "Priya", "customer_phone": phone}
    if consent:
        data["message_ok"] = True
    _sync(
        client,
        h,
        device_id,
        [_ev(oid, "open", data, -20), _ev(oid, "kot", {"kot_no": "C1-1", "lines": [line]}, -19)],
    )
    return oid, line


def _outbox(client, shop):
    return client.get(f"{API}/messages", headers=shop.owner_h).json()["messages"]


def test_no_phone_numbers_in_the_outbox_table():
    """Personal data stays on the order: the outbox points at it."""
    cols = {c["name"] for c in inspect(engine).get_columns("messages")}
    assert not {c for c in cols if "phone" in c or c in ("to", "recipient")}


def test_order_ready_is_messaged_once_and_only_with_consent(client, shop_a, setup, logging_only):
    cat, device, _, _ = setup
    h = shop_a.cashier_h
    oid, line = _takeaway(client, h, device.device_id, cat)
    no, no_line = _takeaway(client, h, device.device_id, cat, consent=False)
    assert _outbox(client, shop_a) == []

    for o, ln in ((oid, line), (no, no_line)):
        _sync(client, h, device.device_id, [_ev(o, "ready", {"line_ids": [ln["line_id"]]}, -5)])
    # Marked ready again (a second kitchen tablet): still one message.
    _sync(client, h, device.device_id, [_ev(oid, "ready", {"line_ids": [line["line_id"]]}, -4)])

    (m,) = _outbox(client, shop_a)
    assert m["kind"] == "ready" and m["order_id"] == oid
    assert m["status"] == "logged"  # no Inkbox key: written down, not sent
    assert "ready" in m["text"].lower() and "Priya" in m["text"]
    assert m["to"] == "••••••3210"  # the owner sees enough to recognise it, not the number
    assert client.get(f"{API}/messages", headers=h).status_code == 403


def test_dine_in_and_partly_ready_orders_are_not_messaged(client, shop_a, setup, logging_only):
    cat, device, t1, _ = setup
    h = shop_a.cashier_h
    oid = str(uuid.uuid4())
    a = _line(cat, 1)
    _sync(
        client,
        h,
        device.device_id,
        [
            _ev(
                oid,
                "open",
                {
                    "order_type": "dine_in",
                    "table_id": t1["id"],
                    "customer_phone": PHONE,
                    "message_ok": True,
                },
                -20,
            ),
            _ev(oid, "kot", {"kot_no": "C1-1", "lines": [a]}, -19),
            _ev(oid, "ready", {"line_ids": [a["line_id"]]}, -10),
        ],
    )
    take, la = _takeaway(client, h, device.device_id, cat)
    extra = _line(cat, 1)
    _sync(
        client,
        h,
        device.device_id,
        [
            _ev(take, "kot", {"kot_no": "C1-2", "lines": [extra]}, -15),
            _ev(take, "ready", {"line_ids": [la["line_id"]]}, -10),
        ],
    )
    assert _outbox(client, shop_a) == []


def test_receipt_link_after_settling(client, shop_a, setup, inkbox):
    cat, device, _, _ = setup
    h = shop_a.cashier_h
    oid, _line1 = _takeaway(client, h, device.device_id, cat)
    bill = device.bill([("Masala tea", 2, [])], payment_mode="upi")
    bill["order_id"] = oid
    _sync(client, h, device.device_id, [_ev(oid, "settle", {"bill_id": bill["id"]}, -1)])
    assert device.sync([bill]).json()["results"][0]["status"] == "accepted"

    (sent,) = inkbox.sent
    assert sent["to"] == "+919876543210"
    assert bill["invoice_no"] in sent["text"]
    link = next(w for w in sent["text"].split() if "/receipt?t=" in w)
    (m,) = _outbox(client, shop_a)
    assert m["kind"] == "receipt" and m["status"] == "sent" and m["provider_id"] == "msg_1"

    # The link opens the receipt without logging in; a changed token does not.
    path = link[link.index("/api/v1/") :]
    page = client.get(path)
    assert page.status_code == 200 and bill["invoice_no"] in page.text and "₹40" in page.text
    assert PHONE not in page.text
    assert client.get(path[:-1] + ("0" if path[-1] != "0" else "1")).status_code == 404


def test_delivery_failures_are_retried_then_given_up(client, shop_a, setup, monkeypatch):
    cat, device, _, _ = setup
    h = shop_a.cashier_h
    monkeypatch.setattr(get_settings(), "inkbox_api_key", "test-not-a-real-key")
    down = FakeInkbox(fail_with=messages.SendError("recipient has not connected"))
    messages.set_transport(down)
    try:
        oid, line = _takeaway(client, h, device.device_id, cat)
        _sync(client, h, device.device_id, [_ev(oid, "ready", {"line_ids": [line["line_id"]]})])
        (m,) = _outbox(client, shop_a)
        assert m["status"] == "pending" and m["attempts"] == 1
        assert "not connected" in m["last_error"]
        for _ in range(messages.MAX_ATTEMPTS):
            client.post(f"{API}/messages/retry", headers=shop_a.owner_h)
        (m,) = _outbox(client, shop_a)
        assert m["status"] == "failed" and m["attempts"] == messages.MAX_ATTEMPTS
    finally:
        messages.set_transport(None)


def test_another_shop_sees_none_of_it(client, shop_a, shop_b, setup, logging_only):
    cat, device, _, _ = setup
    h = shop_a.cashier_h
    oid, line = _takeaway(client, h, device.device_id, cat)
    _sync(client, h, device.device_id, [_ev(oid, "ready", {"line_ids": [line["line_id"]]})])
    assert len(_outbox(client, shop_a)) == 1
    assert _outbox(client, shop_b) == []
