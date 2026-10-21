"""Food courts: customers scan one QR, pick an outlet and order (services/online.py).

What matters most is what a customer with NO login can and cannot reach, and that
two outlets (two shops) never see each other's data."""

import re
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import Message
from tests.conftest import (
    FakeDevice,
    build_catalogue,
    customer_headers,
    make_shop,
    platform_headers,
)

API = "/api/v1"


def _attach(client, admin, court_id, shop):
    r = client.post(
        f"{API}/platform/courts/{court_id}/outlets/attach",
        json={"owner_phone": shop.owner.phone},
        headers=admin,
    )
    assert r.status_code == 201, r.text


@pytest.fixture
def court(client, shop_a, shop_b):
    """A food court the super admin made, with A and B as its outlets; both take orders."""
    build_catalogue(client, shop_a)
    build_catalogue(client, shop_b)
    admin = platform_headers(client)
    made = client.post(f"{API}/platform/courts", json={"name": "Marina Food Court"}, headers=admin)
    assert made.status_code == 201, made.text
    row = made.json()["courts"][0]
    for s in (shop_a, shop_b):
        _attach(client, admin, row["id"], s)
        client.patch(
            f"{API}/food-court/me", json={"accepting_orders": True}, headers=s.owner_h
        ).raise_for_status()
    pub = client.get(f"{API}/public/courts/{row['slug']}").json()
    by_name = {o["name"]: o["id"] for o in pub["outlets"]}
    return {
        "slug": row["slug"],
        "id": row["id"],
        "admin": admin,
        "customer": customer_headers(client),
        "a": by_name[shop_a.shop.name],
        "b": by_name[shop_b.shop.name],
    }


def _menu(client, c, which="a"):
    r = client.get(f"{API}/public/courts/{c['slug']}/outlets/{c[which]}/menu")
    assert r.status_code == 200, r.text
    return {i["name"]: i for i in r.json()["items"]}


def _order(client, c, items, which="a", who=None, **kw):
    body = {
        "request_id": str(uuid.uuid4()),
        "note": "",
        "message_ok": True,
        "items": [{"menu_item_id": i, "qty": q} for i, q in items],
        **kw,
    }
    return client.post(
        f"{API}/public/courts/{c['slug']}/outlets/{c[which]}/orders",
        json=body,
        headers=who or c["customer"],
    )


def _live(client, shop):
    return client.get(f"{API}/orders/live", headers=shop.owner_h).json()["orders"]


def _events(client, shop, order_id, events):
    dev = FakeDevice(client, shop)
    body = [
        {
            "id": str(uuid.uuid4()),
            "order_id": order_id,
            "kind": kind,
            "at": datetime.now(UTC).isoformat(),
            "data": data,
        }
        for kind, data in events
    ]
    r = client.post(
        f"{API}/sync/orders",
        json={"device_id": dev.device_id, "events": body},
        headers=shop.owner_h,
    )
    assert all(x["status"] == "accepted" for x in r.json()["results"]), r.text


# ---------------------------------------------------------------- setup
def test_an_owner_sees_their_court_and_cannot_make_join_or_leave_one(client, shop_a, shop_b, court):
    view = client.get(f"{API}/food-court", headers=shop_a.owner_h).json()
    assert set(view["court"]) == {"id", "name", "slug"}  # no code, no role: nothing to hand out
    assert view["court"]["name"] == "Marina Food Court"
    assert {(o["name"], o["is_me"]) for o in view["outlets"]} == {
        (shop_a.shop.name, True),
        (shop_b.shop.name, False),
    }
    assert client.get(f"{API}/food-court", headers=shop_a.cashier_h).status_code == 403
    # the owner-run routes are gone: making, joining and leaving are the super admin's
    for method, path in (
        ("POST", "/food-court"),
        ("POST", "/food-court/join"),
        ("POST", "/food-court/code"),
        ("DELETE", f"/food-court/outlets/{uuid.uuid4()}"),
    ):
        r = client.request(method, f"{API}{path}", json={}, headers=shop_a.owner_h)
        assert r.status_code in (404, 405), (method, path, r.status_code)


def test_a_shop_not_in_a_court_sees_none(client, shop_a):
    assert client.get(f"{API}/food-court", headers=shop_a.owner_h).json() == {"court": None}
    r = client.patch(
        f"{API}/food-court/me", json={"accepting_orders": True}, headers=shop_a.owner_h
    )
    assert r.status_code == 404


def test_the_catalogue_tells_a_till_it_is_in_a_court(client, shop_a, shop_b):
    build_catalogue(client, shop_a)

    def flag(s):
        return client.get(f"{API}/catalogue", headers=s.cashier_h).json()["shop"]["online_ordering"]

    assert flag(shop_a) is False
    admin = platform_headers(client)
    row = client.post(f"{API}/platform/courts", json={"name": "Court"}, headers=admin).json()[
        "courts"
    ][0]
    _attach(client, admin, row["id"], shop_a)
    assert flag(shop_a) is True and flag(shop_b) is False


# ---------------------------------------------------------------- what a customer can read
def test_the_public_court_shows_names_and_open_only(client, shop_a, shop_b, court):
    pub = client.get(f"{API}/public/courts/{court['slug']}").json()
    assert set(pub) == {"name", "location", "online_payment", "outlets"}
    assert all(set(o) == {"id", "name", "open", "prep_minutes"} for o in pub["outlets"])
    text = str(pub)
    assert str(shop_a.shop.id) not in text and "join_code" not in text
    assert client.get(f"{API}/public/courts/no-such-court-0000").status_code == 404


def test_a_closed_outlet_shows_closed_and_refuses_orders(client, shop_a, court):
    client.patch(f"{API}/food-court/me", json={"accepting_orders": False}, headers=shop_a.owner_h)
    pub = client.get(f"{API}/public/courts/{court['slug']}").json()
    assert {o["name"]: o["open"] for o in pub["outlets"]}[shop_a.shop.name] is False
    tea = _menu(client, court)["Masala tea"]["id"]
    r = _order(client, court, [(tea, 1)])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "outlet_closed"


def test_the_public_menu_shows_only_what_a_customer_needs(client, shop_a, court):
    menu = client.get(f"{API}/public/courts/{court['slug']}/outlets/{court['a']}/menu").json()
    assert set(menu) == {"outlet", "open", "prep_minutes", "gst_type", "items"}
    assert all(
        set(i)
        == {
            "id",
            "name",
            "name_ta",
            "category",
            "price_paise",
            "gst_rate_bp",
            "tax_inclusive",
            "sold_out",
            "description",
            "description_ta",
            "photo_url",
            "is_veg",
            "options",
        }
        for i in menu["items"]
    )
    assert {i["name"] for i in menu["items"]} == {"Masala tea", "Orange juice"}


def test_an_outlet_of_another_court_is_not_found_under_this_one(client, shop_a, court):
    other = make_shop(client, "Elsewhere")
    build_catalogue(client, other)
    made = client.post(
        f"{API}/platform/courts", json={"name": "Elsewhere"}, headers=court["admin"]
    ).json()
    elsewhere = next(c for c in made["courts"] if c["name"] == "Elsewhere")
    _attach(client, court["admin"], elsewhere["id"], other)
    their_outlet = next(
        c
        for c in client.get(f"{API}/platform/courts", headers=court["admin"]).json()["courts"]
        if c["name"] == "Elsewhere"
    )["outlets"][0]["id"]
    r = client.get(f"{API}/public/courts/{court['slug']}/outlets/{their_outlet}/menu")
    assert r.status_code == 404
    assert (
        client.get(f"{API}/public/courts/{court['slug']}/outlets/{uuid.uuid4()}/menu").status_code
        == 404
    )


def test_sold_out_shows_and_blocks_the_order(client, shop_a, court):
    tea = _menu(client, court)["Masala tea"]
    client.patch(
        f"{API}/menu-items/{tea['id']}", json={"is_sold_out": True}, headers=shop_a.owner_h
    ).raise_for_status()
    assert _menu(client, court)["Masala tea"]["sold_out"] is True
    r = _order(client, court, [(tea["id"], 1)])
    assert r.status_code == 409 and r.json()["detail"]["names"] == ["Masala tea"]


# ---------------------------------------------------------------- ordering
def test_an_order_reaches_the_outlets_till_as_a_takeaway_with_a_token(client, shop_a, court):
    menu = _menu(client, court)
    r = _order(client, court, [(menu["Masala tea"]["id"], 2), (menu["Orange juice"]["id"], 1)])
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    assert re.fullmatch(r"[A-Z]{1,2}-1", token)

    (order,) = [o for o in _live(client, shop_a) if o["id"] == r.json()["order_id"]]
    assert order["order_type"] == "takeaway" and order["status"] == "open"
    s = order["state"]
    assert s["customer_name"] == f"{token} Ravi" and s["customer_phone"] == "9840012345"
    assert s["message_ok"] is True
    assert {(ln["name"], ln["qty"], ln["unit_price_paise"]) for ln in s["lines"]} == {
        ("Masala tea", 2, 2000),
        ("Orange juice", 1, 6000),
    }
    # the second order the same day is number 2
    again = _order(client, court, [(menu["Masala tea"]["id"], 1)])
    assert again.json()["token"].endswith("-2")


def test_the_stand_in_author_is_not_a_person_or_a_tablet(client, shop_a, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    _order(client, court, [(tea, 1)]).raise_for_status()
    users = client.get(f"{API}/users", headers=shop_a.owner_h).json()
    assert [u["name"] for u in users] == [
        f"{shop_a.shop.name} owner",
        f"{shop_a.shop.name} cashier",
    ]
    assert [d["code"] for d in client.get(f"{API}/devices", headers=shop_a.owner_h).json()] == [
        "C1"
    ]


def test_the_same_tap_twice_is_one_order(client, shop_a, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    rid = str(uuid.uuid4())
    one = _order(client, court, [(tea, 1)], request_id=rid).json()
    two = _order(client, court, [(tea, 1)], request_id=rid).json()
    assert one == two
    assert len([o for o in _live(client, shop_a) if o["id"] == one["order_id"]]) == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"items": []},
        {"items": [{"menu_item_id": str(uuid.uuid4()), "qty": 0}]},
        {"items": [{"menu_item_id": str(uuid.uuid4()), "qty": 21}]},
    ],
)
def test_bad_orders_are_refused_before_anything_is_written(client, shop_a, court, bad):
    tea = _menu(client, court)["Masala tea"]["id"]
    body = {
        "request_id": str(uuid.uuid4()),
        "items": [{"menu_item_id": tea, "qty": 1}],
        **bad,
    }
    r = client.post(
        f"{API}/public/courts/{court['slug']}/outlets/{court['a']}/orders",
        json=body,
        headers=court["customer"],
    )
    assert r.status_code == 422
    assert _live(client, shop_a) == []


def test_a_dish_from_another_outlet_is_not_orderable_here(client, shop_a, shop_b, court):
    b_tea = _menu(client, court, "b")["Masala tea"]["id"]
    r = _order(client, court, [(b_tea, 1)], which="a")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "items_unavailable"
    assert _live(client, shop_a) == [] and _live(client, shop_b) == []


def test_one_number_cannot_flood_an_outlet(client, shop_a, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    for _ in range(5):
        assert _order(client, court, [(tea, 1)]).status_code == 201
    r = _order(client, court, [(tea, 1)])
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_orders"
    # another number is unaffected
    other = customer_headers(client, "9841100000", "Priya")
    assert _order(client, court, [(tea, 1)], who=other).status_code == 201


# ---------------------------------------------------------------- the customer's own page
def test_the_customer_follows_their_order_to_ready_and_gets_the_message(client, shop_a, court):
    menu = _menu(client, court)
    placed = _order(
        client, court, [(menu["Masala tea"]["id"], 2), (menu["Orange juice"]["id"], 1)]
    ).json()
    key = placed["status_key"]

    seen = client.get(f"{API}/public/orders/{key}").json()
    assert seen["status"] == "received" and seen["token"] == placed["token"]
    assert seen["outlet"] == shop_a.shop.name
    assert seen["total_paise"] == 10000  # 2 teas and a juice, GST included, to the rupee
    assert {(i["name"], i["qty"]) for i in seen["items"]} == {
        ("Masala tea", 2),
        ("Orange juice", 1),
    }

    (order,) = [o for o in _live(client, shop_a) if o["id"] == placed["order_id"]]
    lines = [ln["line_id"] for ln in order["state"]["lines"]]
    _events(client, shop_a, placed["order_id"], [("ready", {"line_ids": lines})])
    assert client.get(f"{API}/public/orders/{key}").json()["status"] == "ready"

    with mark_system(SessionLocal()) as db:  # the existing "your order is ready" message
        ready = db.scalars(select(Message).where(Message.kind == "ready")).all()
    assert len(ready) == 1 and "ready" in ready[0].text


def test_no_message_without_the_customers_yes(client, shop_a, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    placed = _order(client, court, [(tea, 1)], message_ok=False).json()
    (order,) = [o for o in _live(client, shop_a) if o["id"] == placed["order_id"]]
    _events(
        client,
        shop_a,
        placed["order_id"],
        [("ready", {"line_ids": [order["state"]["lines"][0]["line_id"]]})],
    )
    with mark_system(SessionLocal()) as db:
        assert db.scalars(select(Message)).all() == []


def test_a_declined_order_says_so(client, shop_a, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    placed = _order(client, court, [(tea, 1)]).json()
    _events(client, shop_a, placed["order_id"], [("cancel_order", {"reason": "out of milk"})])
    assert client.get(f"{API}/public/orders/{placed['status_key']}").json()["status"] == "declined"


def test_a_changed_or_made_up_status_link_finds_nothing(client, shop_a, shop_b, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    key = _order(client, court, [(tea, 1)]).json()["status_key"]
    assert client.get(f"{API}/public/orders/{key}").status_code == 200
    flipped = key[:-1] + ("0" if key[-1] != "0" else "1")
    for bad in (flipped, key[:64], "x" * 96, uuid.uuid4().hex * 3, "../../etc/passwd"):
        assert client.get(f"{API}/public/orders/{bad}").status_code == 404
    # B's shop id with A's order id: a different key, not a different answer
    forged = shop_b.shop.id.hex + key[32:]
    assert client.get(f"{API}/public/orders/{forged}").status_code == 404


def test_an_order_stays_in_its_own_outlet(client, shop_a, shop_b, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    placed = _order(client, court, [(tea, 1)]).json()
    assert [o["id"] for o in _live(client, shop_a)] == [placed["order_id"]]
    assert _live(client, shop_b) == []


def test_sold_out_ends_with_the_day(client, shop_a, court, monkeypatch):
    from app.core.config import get_settings
    from app.core.time import business_date

    monkeypatch.setattr(get_settings(), "cron_secret", "s3cret")
    tea = _menu(client, court)["Masala tea"]["id"]
    client.patch(
        f"{API}/menu-items/{tea}", json={"is_sold_out": True}, headers=shop_a.owner_h
    ).raise_for_status()
    assert _menu(client, court)["Masala tea"]["sold_out"] is True
    r = client.get(
        f"{API}/cron/daily?today={business_date(datetime.now(UTC)).isoformat()}",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 200, r.text
    assert _menu(client, court)["Masala tea"]["sold_out"] is False
