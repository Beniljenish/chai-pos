"""Shifts and the cash drawer.

Hand-worked drawer (one shift on one tablet):
    opening float                         Rs 500.00
    cash bills: Masala tea x1  (Rs 20)    + 20.00
                Masala tea x2  (Rs 40)    voided: not counted, listed separately
    UPI bill:   Orange juice   (Rs 60)    not cash: listed, not in the drawer
    paid out:   milkman                   - 300.00
    paid in:    change from the bank      + 100.00
    expected in the drawer                = 320.00
    counted                                 318.00  -> Rs 2 short
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import FakeDevice, build_catalogue

API = "/api/v1"


def _now(minutes=0):
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()


def _sync(client, h, device_id, ops):
    r = client.post(f"{API}/sync/shifts", json={"device_id": str(device_id), "ops": ops}, headers=h)
    assert r.status_code == 200, r.text
    return [(x["status"], x["reason"]) for x in r.json()["results"]]


def _open(shift_id, float_paise=50000, at=None, **kw):
    return {
        "op": "open",
        "id": str(shift_id),
        "at": at or _now(-60),
        "opening_float_paise": float_paise,
        **kw,
    }


def _cash(shift_id, kind, amount, reason, **kw):
    return {
        "op": "cash",
        "id": str(uuid.uuid4()),
        "shift_id": str(shift_id),
        "at": _now(-30),
        "kind": kind,
        "amount_paise": amount,
        "reason": reason,
        **kw,
    }


def _close(shift_id, counted, at=None, **kw):
    return {
        "op": "close",
        "id": str(uuid.uuid4()),
        "shift_id": str(shift_id),
        "at": at or _now(),
        "counted_cash_paise": counted,
        **kw,
    }


@pytest.fixture
def device(client, shop_a):
    build_catalogue(client, shop_a)
    return FakeDevice(client, shop_a)


def _bill(device, items, shift_id, mode="cash"):
    b = device.bill(items, payment_mode=mode)
    b["shift_id"] = str(shift_id)
    return b


def test_hand_worked_drawer(client, shop_a, device):
    h = shop_a.cashier_h
    sid = uuid.uuid4()
    assert _sync(client, h, device.device_id, [_open(sid)]) == [("accepted", None)]

    tea = _bill(device, [("Masala tea", 1, [])], sid)
    twice = _bill(device, [("Masala tea", 2, [])], sid)
    juice = _bill(device, [("Orange juice", 1, [])], sid, mode="upi")
    assert all(
        r["status"] == "accepted" for r in device.sync([tea, twice, juice]).json()["results"]
    )
    client.post(
        f"{API}/bills/{twice['id']}/void", json={"reason": "duplicate"}, headers=shop_a.owner_h
    ).raise_for_status()

    assert (
        _sync(
            client,
            h,
            device.device_id,
            [
                _cash(sid, "pay_out", 30000, "Milkman"),
                _cash(sid, "pay_in", 10000, "Change from the bank"),
                _close(sid, 31800, note="one coin missing?"),
            ],
        )
        == [("accepted", None)] * 3
    )

    rep = client.get(f"{API}/shifts", headers=shop_a.owner_h).json()
    (s,) = rep["shifts"]
    assert s["opening_float_paise"] == 50000
    assert (s["cash_paise"], s["upi_paise"], s["voided_cash_paise"]) == (2000, 6000, 4000)
    assert (s["paid_out_paise"], s["paid_in_paise"]) == (30000, 10000)
    assert s["expected_cash_paise"] == 32000
    assert s["counted_cash_paise"] == 31800
    assert s["difference_paise"] == -200
    assert s["bills"] == 2
    assert s["opened_by_name"] == s["closed_by_name"] == "Shop A cashier"
    assert [m["reason"] for m in s["movements"]] == ["Milkman", "Change from the bank"]
    assert s["close_note"] == "one coin missing?"
    got = client.get(f"{API}/bills/{tea['id']}", headers=shop_a.owner_h).json()
    assert got["shift_id"] == str(sid)
    assert rep["cash_outside_shifts"] == {"bills": 0, "total_paise": 0}


def test_retries_are_harmless_and_changed_content_is_refused(client, shop_a, device):
    h = shop_a.cashier_h
    sid = uuid.uuid4()
    opened = _open(sid)
    out = _cash(sid, "pay_out", 30000, "Milkman")
    close = _close(sid, 50000)
    ops = [opened, out, close]
    assert _sync(client, h, device.device_id, ops) == [("accepted", None)] * 3
    assert _sync(client, h, device.device_id, ops) == [("duplicate", None)] * 3
    assert _sync(client, h, device.device_id, [{**opened, "opening_float_paise": 1}]) == [
        ("rejected", "id_reused_with_different_content")
    ]
    assert _sync(client, h, device.device_id, [_close(sid, 99999)]) == [
        ("rejected", "already_closed")
    ]
    rep = client.get(f"{API}/shifts", headers=shop_a.owner_h).json()
    assert rep["shifts"][0]["counted_cash_paise"] == 50000


def test_impossible_operations_are_refused(client, shop_a, device):
    h = shop_a.cashier_h
    sid = uuid.uuid4()
    assert _sync(client, h, device.device_id, [_open(sid, at=_now(30))]) == [
        ("rejected", "device_clock_ahead")
    ]
    assert _sync(client, h, device.device_id, [_cash(uuid.uuid4(), "pay_out", 100, "x")]) == [
        ("rejected", "unknown_shift")
    ]
    _sync(client, h, device.device_id, [_open(sid, at=_now(-5))])
    assert _sync(client, h, device.device_id, [_close(sid, 0, at=_now(-60))]) == [
        ("rejected", "closed_before_opened")
    ]


def test_a_shift_belongs_to_its_tablet(client, shop_a, device):
    other = client.post(
        f"{API}/devices", json={"name": "Back counter"}, headers=shop_a.owner_h
    ).json()
    sid = uuid.uuid4()
    _sync(client, shop_a.cashier_h, device.device_id, [_open(sid)])
    # Another tablet cannot pay out of, or close, this drawer...
    assert _sync(client, shop_a.cashier_h, other["id"], [_close(sid, 0)]) == [
        ("rejected", "unknown_shift")
    ]
    # ...nor put its bills in it.
    second = FakeDevice(client, shop_a, device_id=other["id"], code=other["code"])
    b = _bill(second, [("Masala tea", 1, [])], sid)
    second.sync([b]).raise_for_status()
    assert client.get(f"{API}/bills/{b['id']}", headers=shop_a.owner_h).json()["shift_id"] is None
    rep = client.get(f"{API}/shifts", headers=shop_a.owner_h).json()
    assert rep["cash_outside_shifts"] == {"bills": 1, "total_paise": 2000}


def test_a_bill_whose_shift_never_arrived_is_still_accepted(client, shop_a, device):
    b = _bill(device, [("Masala tea", 1, [])], uuid.uuid4())
    assert device.sync([b]).json()["results"][0]["status"] == "accepted"
    rep = client.get(f"{API}/shifts", headers=shop_a.owner_h).json()
    assert rep["shifts"] == [] and rep["cash_outside_shifts"]["total_paise"] == 2000
    # Retrying it unchanged is a harmless duplicate.
    assert device.sync([b]).json()["results"][0]["status"] == "duplicate"


def test_shift_is_credited_to_who_opened_and_closed_it(client, shop_a, device):
    ravi = client.post(
        f"{API}/users",
        json={"name": "Ravi", "phone": "9876500001", "password": "ginger4821"},
        headers=shop_a.owner_h,
    ).json()
    sid = uuid.uuid4()
    # Ravi opened it offline; the owner's login later sends it; the owner closes.
    _sync(client, shop_a.owner_h, device.device_id, [_open(sid, cashier_id=ravi["id"])])
    _sync(client, shop_a.owner_h, device.device_id, [_close(sid, 50000)])
    (s,) = client.get(f"{API}/shifts", headers=shop_a.owner_h).json()["shifts"]
    assert (s["opened_by_name"], s["closed_by_name"]) == ("Ravi", "Shop A owner")


def test_tablet_learns_its_open_shift_and_the_last_count(client, shop_a, device):
    url = f"{API}/devices/{device.device_id}/sync-state"
    state = client.get(url, headers=shop_a.cashier_h).json()
    assert state["open_shift"] is None and state["last_counted"] is None
    sid = uuid.uuid4()
    _sync(client, shop_a.cashier_h, device.device_id, [_open(sid, 40000)])
    state = client.get(url, headers=shop_a.cashier_h).json()
    assert state["open_shift"]["id"] == str(sid)
    assert state["open_shift"]["opening_float_paise"] == 40000
    assert state["open_shift"]["opened_by_name"] == "Shop A cashier"
    _sync(client, shop_a.cashier_h, device.device_id, [_close(sid, 123400)])
    state = client.get(url, headers=shop_a.cashier_h).json()
    assert state["open_shift"] is None
    assert state["last_counted"]["counted_cash_paise"] == 123400


def test_report_is_owner_only_and_per_shop(client, shop_a, shop_b, device):
    _sync(client, shop_a.cashier_h, device.device_id, [_open(uuid.uuid4())])
    assert client.get(f"{API}/shifts", headers=shop_a.cashier_h).status_code == 403
    assert client.get(f"{API}/shifts", headers=shop_b.owner_h).json()["shifts"] == []
    # Shop B cannot sync into shop A's tablet.
    r = client.post(
        f"{API}/sync/shifts",
        json={"device_id": str(device.device_id), "ops": [_open(uuid.uuid4())]},
        headers=shop_b.owner_h,
    )
    assert r.status_code == 404


def test_shop_can_switch_shifts_off(client, shop_a):
    r = client.patch(f"{API}/shop", json={"cash_shifts": False}, headers=shop_a.owner_h)
    assert r.status_code == 200 and r.json()["cash_shifts"] is False
    build_catalogue(client, shop_a)
    cat = client.get(f"{API}/catalogue", headers=shop_a.cashier_h).json()
    assert cat["shop"]["cash_shifts"] is False


def test_daily_email_says_whether_each_drawer_matched(client, shop_a, device):
    from app.core.time import business_date, utcnow
    from app.db.session import SessionLocal
    from app.db.tenancy import bind_tenant
    from app.services.reports import daily_figures

    a, b = uuid.uuid4(), uuid.uuid4()
    _sync(client, shop_a.cashier_h, device.device_id, [_open(a, 50000), _close(a, 49800)])
    _sync(client, shop_a.cashier_h, device.device_id, [_open(b, 49800)])
    with SessionLocal() as s:
        bind_tenant(s, shop_a.shop.id)
        lines = daily_figures(s, business_date(utcnow()))["shifts"]
    assert lines == [
        "Shop A cashier: ₹2 short (counted ₹498)",
        "Shop A cashier: shift not ended (cash not counted)",
    ]
