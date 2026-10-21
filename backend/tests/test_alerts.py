"""The owner's "needs you" list (services/alerts.py): derived from the records,
each rule on its own, owner only, and never another shop's."""

import uuid
from datetime import UTC, datetime

import pytest

from app.core.time import business_date
from tests.conftest import FakeDevice, build_catalogue
from tests.test_phase7 import _stock_in
from tests.test_shifts import _close, _day, _open, _sync

API = "/api/v1"


@pytest.fixture
def cat(client, shop_a):
    return build_catalogue(client, shop_a)


@pytest.fixture
def device(client, shop_a, cat):
    return FakeDevice(client, shop_a)


def _alerts(client, shop, day=None):
    day = day or business_date(datetime.now(UTC)).isoformat()
    r = client.get(f"{API}/reports/alerts?business_date={day}", headers=shop.owner_h)
    assert r.status_code == 200, r.text
    return {a["kind"]: a for a in r.json()["alerts"]}


def _accept(device, bill):
    assert device.sync([bill]).json()["results"][0]["status"] == "accepted"
    return bill


def test_owner_only(client, shop_a):
    assert client.get(f"{API}/reports/alerts", headers=shop_a.cashier_h).status_code == 403


def test_a_quiet_day_has_nothing_to_say(client, shop_a, device):
    _accept(device, device.bill([("Masala tea", 1, [])]))
    assert _alerts(client, shop_a) == {}


def test_a_short_drawer_is_an_alert_and_a_small_gap_is_not(client, shop_a, device):
    h = shop_a.cashier_h
    short = uuid.uuid4()
    _sync(client, h, device.device_id, [_open(short), _close(short, 47000)])  # 30 rupees short
    got = _alerts(client, shop_a, _day())["drawer_short"]
    assert got["urgency"] == "act" and got["title"] == "Drawer short by ₹30"
    assert "₹500" in got["detail"] and "₹470" in got["detail"]


def test_three_voids_in_an_hour_by_one_person(client, shop_a, device):
    bills = [_accept(device, device.bill([("Masala tea", 1, [])])) for _ in range(3)]
    for b in bills[:2]:
        client.post(
            f"{API}/bills/{b['id']}/void", json={"reason": "wrong_item"}, headers=shop_a.owner_h
        ).raise_for_status()
    assert "void_burst" not in _alerts(client, shop_a)  # two is ordinary
    client.post(
        f"{API}/bills/{bills[2]['id']}/void", json={"reason": "wrong_item"}, headers=shop_a.owner_h
    ).raise_for_status()
    got = _alerts(client, shop_a)["void_burst"]
    assert got["title"] == "3 voids in one hour" and "₹60" in got["detail"]


def test_discounts_far_above_the_usual(client, shop_a, device):
    _accept(device, device.bill([("Orange juice", 3, [])], bill_discount=6000, reason=""))
    got = _alerts(client, shop_a)["discounts"]
    assert got["urgency"] == "look"
    assert "₹60 given today" in got["detail"] and "1 with no reason" in got["detail"]


def test_small_discounts_are_not_an_alert(client, shop_a, device):
    _accept(device, device.bill([("Orange juice", 3, [])], bill_discount=4000, reason="regular"))
    assert "discounts" not in _alerts(client, shop_a)


def test_large_wastage_waiting_for_the_owner(client, shop_a, cat):
    _stock_in(client, shop_a, cat.milk["id"], 10000, 56000)
    client.patch(
        f"{API}/shop", json={"wastage_approval_paise": 5000}, headers=shop_a.owner_h
    ).raise_for_status()
    client.post(
        f"{API}/wastage",
        json={"ingredient_id": cat.milk["id"], "qty": "1000", "reason": "spoiled"},
        headers=shop_a.cashier_h,
    ).raise_for_status()
    got = _alerts(client, shop_a)["wastage_pending"]
    assert got["urgency"] == "act" and got["section"] == "dayend"
    assert got["title"] == "1 large wastage entry waiting"


def test_an_ingredient_price_rise_is_news_not_a_warning(client, shop_a, cat):
    _stock_in(client, shop_a, cat.milk["id"], 10000, 54000)  # 5.4 paise/ml = Rs 54 a litre
    _stock_in(client, shop_a, cat.milk["id"], 10000, 58000)  # Rs 58 a litre
    got = _alerts(client, shop_a)["price_up"]
    assert got["urgency"] == "info" and got["period"] == "week"
    assert got["title"] == "Milk cost went up 7%"
    assert got["detail"].startswith("₹54 → ₹58 per litre")


def test_a_price_change_under_five_percent_is_ignored(client, shop_a, cat):
    _stock_in(client, shop_a, cat.milk["id"], 10000, 54000)
    _stock_in(client, shop_a, cat.milk["id"], 10000, 55000)
    assert "price_up" not in _alerts(client, shop_a)


def test_most_urgent_first_and_never_another_shops(client, shop_a, shop_b, cat, device):
    _stock_in(client, shop_a, cat.milk["id"], 10000, 54000)
    _stock_in(client, shop_a, cat.milk["id"], 10000, 58000)
    _accept(device, device.bill([("Orange juice", 3, [])], bill_discount=6000, reason=""))
    order = [
        a["urgency"]
        for a in client.get(f"{API}/reports/alerts", headers=shop_a.owner_h).json()["alerts"]
    ]
    assert order == ["look", "info"]
    assert client.get(f"{API}/reports/alerts", headers=shop_b.owner_h).json() == {"alerts": []}


def test_a_gap_under_twenty_rupees_is_a_miscounted_coin(client, shop_a, device):
    sid = uuid.uuid4()
    _sync(client, shop_a.cashier_h, device.device_id, [_open(sid), _close(sid, 48500)])  # Rs 15
    assert "drawer_short" not in _alerts(client, shop_a, _day())
