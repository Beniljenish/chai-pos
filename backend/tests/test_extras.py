# ruff: noqa: F811  (fixtures imported from other test modules are used as arguments)
"""Favourites, order again, wait time and ratings for food court customers (services/extras.py)."""

import uuid

from tests.conftest import customer_headers
from tests.test_food_court import API, _events, _live, _menu, _order, court  # noqa: F401


def _mine(client, c, who=None):
    return client.get(f"{API}/customer/favourites", headers=who or c["customer"]).json()[
        "favourites"
    ]


# ---------------------------------------------------------------- favourites
def test_a_customer_hearts_and_unhearts_a_dish(client, shop_a, court):
    tea = _menu(client, court)["Masala tea"]
    r = client.put(f"{API}/customer/favourites/{tea['id']}", headers=court["customer"])
    assert r.status_code == 200
    (fav,) = r.json()["favourites"]
    assert fav["name"] == "Masala tea" and fav["price_paise"] == 2000
    assert fav["outlet"] == shop_a.shop.name and fav["court_slug"] == court["slug"]
    assert fav["outlet_id"] == court["a"] and fav["is_veg"] is True and fav["sold_out"] is False
    # hearting twice is still one
    client.put(f"{API}/customer/favourites/{tea['id']}", headers=court["customer"])
    assert len(_mine(client, court)) == 1
    gone = client.delete(f"{API}/customer/favourites/{tea['id']}", headers=court["customer"])
    assert gone.json()["favourites"] == []
    # removing what is not there is fine
    assert (
        client.delete(
            f"{API}/customer/favourites/{tea['id']}", headers=court["customer"]
        ).status_code
        == 200
    )


def test_favourites_are_private_and_need_an_account(client, shop_a, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    client.put(f"{API}/customer/favourites/{tea}", headers=court["customer"])
    other = customer_headers(client, "9841100000", "Priya")
    assert _mine(client, court, other) == []
    assert client.get(f"{API}/customer/favourites").status_code == 401
    for h in (shop_a.owner_h, court["admin"]):
        assert client.get(f"{API}/customer/favourites", headers=h).status_code == 401
        assert client.put(f"{API}/customer/favourites/{tea}", headers=h).status_code == 401


def test_only_a_real_dish_in_a_court_can_be_a_favourite(client, shop_a, court):
    r = client.put(f"{API}/customer/favourites/{uuid.uuid4()}", headers=court["customer"])
    assert r.status_code == 404
    # a dish switched off disappears from the list instead of leaving a dead heart
    tea = _menu(client, court)["Masala tea"]["id"]
    client.put(f"{API}/customer/favourites/{tea}", headers=court["customer"])
    client.patch(f"{API}/menu-items/{tea}", json={"is_active": False}, headers=shop_a.owner_h)
    assert _mine(client, court) == []


def test_a_sold_out_favourite_says_so(client, shop_a, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    client.put(f"{API}/customer/favourites/{tea}", headers=court["customer"])
    client.patch(f"{API}/menu-items/{tea}", json={"is_sold_out": True}, headers=shop_a.owner_h)
    assert _mine(client, court)[0]["sold_out"] is True


# ---------------------------------------------------------------- order again
def test_my_orders_carry_what_order_again_needs(client, shop_a, court):
    menu = _menu(client, court)
    placed = _order(
        client, court, [(menu["Masala tea"]["id"], 2), (menu["Orange juice"]["id"], 1)]
    ).json()
    (row,) = client.get(f"{API}/customer/orders", headers=court["customer"]).json()["orders"]
    assert row["outlet_id"] == court["a"] and row["court_slug"] == court["slug"]
    assert sorted(
        (ln["menu_item_id"], ln["qty"], ln["modifier_ids"]) for ln in row["lines"]
    ) == sorted([(menu["Masala tea"]["id"], 2, []), (menu["Orange juice"]["id"], 1, [])])
    assert row["rating"] is None and row["paid_online"] is False
    assert row["status_key"] == placed["status_key"]


# ---------------------------------------------------------------- wait time
def test_an_owner_sets_the_usual_wait_and_customers_see_it(client, shop_a, court):
    r = client.patch(f"{API}/food-court/me", json={"prep_minutes": 12}, headers=shop_a.owner_h)
    assert r.status_code == 200 and r.json()["prep_minutes"] == 12
    assert r.json()["accepting_orders"] is True  # untouched: only what was sent changes
    pub = client.get(f"{API}/public/courts/{court['slug']}").json()
    assert {o["prep_minutes"] for o in pub["outlets"] if o["id"] == court["a"]} == {12}
    menu = client.get(f"{API}/public/courts/{court['slug']}/outlets/{court['a']}/menu").json()
    assert menu["prep_minutes"] == 12
    # 0 means "not said"
    r = client.patch(f"{API}/food-court/me", json={"prep_minutes": 0}, headers=shop_a.owner_h)
    assert r.json()["prep_minutes"] is None


def test_the_wait_time_is_bounded_and_the_owners_alone_to_set(client, shop_a, court):
    for bad in (-1, 181):
        r = client.patch(f"{API}/food-court/me", json={"prep_minutes": bad}, headers=shop_a.owner_h)
        assert r.status_code == 422
    r = client.patch(f"{API}/food-court/me", json={"prep_minutes": 5}, headers=shop_a.cashier_h)
    assert r.status_code == 403


# ---------------------------------------------------------------- ratings
def _collect(client, shop, order_id):
    order = next(o for o in _live(client, shop) if o["id"] == order_id)
    lines = [ln["line_id"] for ln in order["state"]["lines"]]
    _events(
        client,
        shop,
        order_id,
        [("ready", {"line_ids": lines}), ("settle", {"bill_id": str(uuid.uuid4()), "parts": 1})],
    )


def _rate(client, key, who, rating=5, comment=""):
    return client.post(
        f"{API}/customer/orders/{key}/rating",
        json={"rating": rating, "comment": comment},
        headers=who,
    )


def test_a_collected_order_can_be_rated_once_by_the_customer_who_placed_it(client, shop_a, court):
    placed = _order(client, court, [(_menu(client, court)["Masala tea"]["id"], 1)]).json()
    key = placed["status_key"]
    early = _rate(client, key, court["customer"], 5)
    assert early.status_code == 409 and early.json()["detail"]["code"] == "not_collected"

    _collect(client, shop_a, placed["order_id"])
    assert client.get(f"{API}/public/orders/{key}").json()["status"] == "collected"
    assert client.get(f"{API}/customer/orders/{key}/rating", headers=court["customer"]).json() == {
        "rating": None,
        "comment": "",
    }
    ok = _rate(client, key, court["customer"], 4, "  Tea great, idli a bit cold ")
    assert ok.status_code == 201 and ok.json() == {"rating": 4}
    again = _rate(client, key, court["customer"], 1)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_rated"
    mine = client.get(f"{API}/customer/orders/{key}/rating", headers=court["customer"]).json()
    assert mine == {"rating": 4, "comment": "Tea great, idli a bit cold"}
    (row,) = client.get(f"{API}/customer/orders", headers=court["customer"]).json()["orders"]
    assert row["rating"] == 4


def test_nobody_else_can_rate_or_read_someones_rating(client, shop_a, court):
    placed = _order(client, court, [(_menu(client, court)["Masala tea"]["id"], 1)]).json()
    key = placed["status_key"]
    _collect(client, shop_a, placed["order_id"])
    other = customer_headers(client, "9841100000", "Priya")
    assert _rate(client, key, other).status_code == 404
    assert client.get(f"{API}/customer/orders/{key}/rating", headers=other).status_code == 404
    assert _rate(client, key, {}).status_code == 401
    assert _rate(client, key, shop_a.owner_h).status_code == 401
    assert _rate(client, "0" * 96, court["customer"]).status_code == 404


def test_a_rating_is_one_to_five_and_the_comment_is_short(client, shop_a, court):
    placed = _order(client, court, [(_menu(client, court)["Masala tea"]["id"], 1)]).json()
    _collect(client, shop_a, placed["order_id"])
    for bad in (0, 6, -1):
        assert _rate(client, placed["status_key"], court["customer"], bad).status_code == 422
    long = _rate(client, placed["status_key"], court["customer"], 3, "x" * 201)
    assert long.status_code == 422


def test_owner_and_admin_see_the_ratings(client, shop_a, shop_b, court):
    for who, n in (
        (court["customer"], 1),
        (customer_headers(client, "9841100000", "Priya Raj"), 2),
    ):
        placed = _order(
            client, court, [(_menu(client, court)["Masala tea"]["id"], 1)], who=who
        ).json()
        _collect(client, shop_a, placed["order_id"])
        _rate(client, placed["status_key"], who, 5 if n == 1 else 4, f"order {n}")
    mine = client.get(f"{API}/food-court", headers=shop_a.owner_h).json()["ratings"]
    assert mine["count"] == 2 and mine["average"] == 4.5
    assert {r["comment"] for r in mine["recent"]} == {"order 1", "order 2"}
    assert {r["name"] for r in mine["recent"]} == {"Ravi", "Priya"}  # first names only
    # another outlet of the same court sees none of it
    theirs = client.get(f"{API}/food-court", headers=shop_b.owner_h).json()["ratings"]
    assert theirs == {"average": None, "count": 0, "recent": []}
    # the admin sees every outlet's average
    courts = client.get(f"{API}/platform/courts", headers=court["admin"]).json()["courts"]
    outlets = {o["name"]: o for o in courts[0]["outlets"]}
    assert (
        outlets[shop_a.shop.name]["rating"] == 4.5
        and outlets[shop_a.shop.name]["rating_count"] == 2
    )
    assert (
        outlets[shop_b.shop.name]["rating"] is None
        and outlets[shop_b.shop.name]["rating_count"] == 0
    )
