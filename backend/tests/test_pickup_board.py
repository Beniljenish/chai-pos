# ruff: noqa: F811  (fixtures imported from other test modules are used as arguments)
"""Pickup time slots, the table QR and the food court's display board (README, "9.17")."""

import uuid

import pytest

from tests.test_food_court import API, _events, _live, _menu, _order, court  # noqa: F401
from tests.test_online_payments import _pay, _start, rzp  # noqa: F401


def _slots(client, c, which="a"):
    r = client.get(f"{API}/public/courts/{c['slug']}/outlets/{c[which]}/slots")
    assert r.status_code == 200, r.text
    got = r.json()
    if got["enabled"] and not got["slots"]:
        pytest.skip("too close to midnight for any slot today")
    return got


def _tea(client, c, which="a"):
    return _menu(client, c, which)["Masala tea"]["id"]


def test_slots_are_quarter_hours_in_the_near_future(client, court):
    got = _slots(client, court)
    assert got["enabled"] is True
    ats = [s["at"] for s in got["slots"]]
    assert ats == sorted(ats) and len(ats) <= 12 + 1
    assert all(a[14:16] in ("00", "15", "30", "45") for a in ats)  # (UTC offset is whole quarters)
    assert not any(s["full"] for s in got["slots"])


def test_an_order_for_a_time_waits_with_that_time_and_a_table_name(client, shop_a, court):
    at = _slots(client, court)["slots"][1]["at"]
    r = _order(client, court, [(_tea(client, court), 1)], pickup_at=at, table_name="Table 4")
    assert r.status_code == 201, r.text
    oid = _live(client, shop_a)[0]["id"]
    extra = client.get(f"{API}/orders/online-paid", headers=shop_a.owner_h).json()
    assert extra["table"] == {oid: "Table 4"}
    assert extra["pickup"][oid][:16] == at[:16].replace("T", "T")


def test_a_time_that_is_not_a_slot_is_refused(client, court):
    at = _slots(client, court)["slots"][1]["at"]
    odd = at[:14] + "07" + at[16:]
    r = _order(client, court, [(_tea(client, court), 1)], pickup_at=odd)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "slot_gone"


def test_a_full_slot_is_marked_and_refused(client, shop_a, court):
    client.patch(
        f"{API}/food-court/me", json={"pickup_capacity": 1}, headers=shop_a.owner_h
    ).raise_for_status()
    at = _slots(client, court)["slots"][1]["at"]
    first = _order(client, court, [(_tea(client, court), 1)], pickup_at=at)
    assert first.status_code == 201, first.text
    marked = {s["at"]: s["full"] for s in _slots(client, court)["slots"]}
    assert marked[at] is True
    second = _order(client, court, [(_tea(client, court), 1)], pickup_at=at)
    assert second.status_code == 409 and second.json()["detail"]["code"] == "slot_full"
    # a cancelled order frees the slot
    _events(client, shop_a, _live(client, shop_a)[0]["id"], [("cancel_order", {"reason": "test"})])
    assert {s["at"]: s["full"] for s in _slots(client, court)["slots"]}[at] is False


def test_an_outlet_can_switch_pickup_times_off(client, shop_a, court):
    client.patch(
        f"{API}/food-court/me", json={"pickup_enabled": False}, headers=shop_a.owner_h
    ).raise_for_status()
    assert _slots(client, court)["enabled"] is False
    at = _slots(client, court, "b")["slots"][1]["at"]
    r = _order(client, court, [(_tea(client, court), 1)], pickup_at=at)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "pickup_off"


def test_a_paid_order_keeps_its_time_through_payment(client, shop_a, court, rzp):
    at = _slots(client, court)["slots"][1]["at"]
    cart = {
        "outlet_id": court["a"],
        "request_id": str(uuid.uuid4()),
        "note": "",
        "pickup_at": at,
        "table_name": "T2",
        "items": [{"menu_item_id": _tea(client, court), "qty": 1}],
    }
    started = client.post(
        f"{API}/customer/checkout",
        json={"checkout_id": str(uuid.uuid4()), "slug": court["slug"], "orders": [cart]},
        headers=court["customer"],
    )
    assert started.status_code == 201, started.text
    _pay(client, rzp, started.json())
    extra = client.get(f"{API}/orders/online-paid", headers=shop_a.owner_h).json()
    oid = _live(client, shop_a)[0]["id"]
    assert extra["table"][oid] == "T2" and oid in extra["pickup"] and oid in extra["paid"]
    assert _start  # (imported for the fixtures' sake)


def test_the_board_shows_tokens_only_and_when_they_are_ready(client, shop_a, court):
    board = f"{API}/public/courts/{court['slug']}/board"
    assert client.get(board).json()["ready"] == []  # no login needed
    r = _order(client, court, [(_tea(client, court), 1)])
    token = r.json()["token"]
    got = client.get(board).json()
    assert [m["token"] for m in got["making"]] == [token] and got["ready"] == []
    live = _live(client, shop_a)[0]
    line_ids = [ln["line_id"] for ln in live["state"]["lines"]]
    _events(client, shop_a, live["id"], [("ready", {"line_ids": line_ids})])
    got = client.get(board).json()
    assert [m["token"] for m in got["ready"]] == [token] and got["making"] == []
    # nothing personal leaves the server
    text = client.get(board).text
    assert "phone" not in text and "customer" not in text.lower().replace("customer_", "")
    assert client.get(f"{API}/public/courts/nope/board").status_code == 404


def test_a_scheduled_order_is_not_being_made_until_its_time_is_near(client, court):
    slots = _slots(client, court)["slots"]
    far = slots[-1]["at"]
    if len(slots) < 8:
        pytest.skip("too close to midnight for a far slot")
    _order(client, court, [(_tea(client, court), 1)], pickup_at=far).raise_for_status()
    got = client.get(f"{API}/public/courts/{court['slug']}/board").json()
    assert got["making"] == [] and got["ready"] == []
