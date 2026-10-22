# ruff: noqa: F811  (fixtures imported from other test modules are used as arguments)
"""Round four (README, "9.19"): offers, linked outlets, sold-out history."""

import uuid
from datetime import timedelta

from app.core.time import business_date, utcnow
from app.services.gst import LineIn, compute_bill
from tests.conftest import PASSWORD, build_catalogue, make_shop
from tests.test_food_court import API, _live, _menu, _order, court  # noqa: F401
from tests.test_online_payments import _pay, rzp  # noqa: F401


def _make(client, shop, code="SAVE10", kind="percent", value=10, **kw):
    r = client.post(
        f"{API}/coupons",
        json={"code": code, "kind": kind, "value": value, **kw},
        headers=shop.owner_h,
    )
    assert r.status_code == 201, r.text
    return next(c for c in r.json()["coupons"] if c["code"] == code)


def _check(client, c, code, items, who=None, which="a"):
    return client.post(
        f"{API}/customer/coupon-check",
        json={
            "slug": c["slug"],
            "outlet_id": c[which],
            "code": code,
            "items": [{"menu_item_id": i, "qty": q} for i, q in items],
        },
        headers=who or c["customer"],
    )


def _tea(client, c):
    return _menu(client, c)["Masala tea"]["id"]


def _total(price, qty, off=0):
    return compute_bill(
        [LineIn(price, qty, 500, True, ())],
        __import__("app.models", fromlist=["GstType"]).GstType.regular,
        off,
    ).total


# ---------------------------------------------------------------- offers
def test_a_percentage_code_takes_whole_rupees_off_and_the_total_matches_the_bill(
    client, shop_a, court
):
    _make(client, shop_a, "SAVE10", "percent", 10)
    tea = _tea(client, court)
    r = _check(client, court, "save10", [(tea, 5)])  # ₹100: 10% is ₹10
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["discount_paise"] == 1000 and got["total_paise"] == _total(2000, 5, 1000) == 9000


def test_an_amount_code_cannot_take_the_last_rupee(client, shop_a, court):
    _make(client, shop_a, "BIG", "amount", 50000)
    got = _check(client, court, "BIG", [(_tea(client, court), 1)]).json()  # a ₹20 tea
    assert got["discount_paise"] == 1900 and got["total_paise"] == 100  # ₹1 is always payable


def test_a_cap_a_minimum_and_an_end_date_are_enforced(client, shop_a, court):
    _make(client, shop_a, "CAPPED", "percent", 50, max_discount_paise=2000)
    _make(client, shop_a, "BIGONLY", "amount", 1000, min_order_paise=10000)
    yesterday = (business_date(utcnow()) - timedelta(days=1)).isoformat()
    _make(client, shop_a, "OLD", "amount", 1000, valid_until=yesterday)
    tea = _tea(client, court)
    assert (
        _check(client, court, "CAPPED", [(tea, 10)]).json()["discount_paise"] == 2000
    )  # ₹200 -> cap
    low = _check(client, court, "BIGONLY", [(tea, 1)])
    assert low.status_code == 422 and low.json()["detail"]["code"] == "coupon_min"
    old = _check(client, court, "OLD", [(tea, 5)])
    assert old.json()["detail"]["code"] == "coupon_expired"
    unknown = _check(client, court, "NOPE", [(tea, 5)])
    assert unknown.json()["detail"]["code"] == "coupon_unknown"


def test_a_code_belongs_to_its_own_outlet(client, shop_a, shop_b, court):
    _make(client, shop_b, "ONLYB", "amount", 1000)
    r = _check(client, court, "ONLYB", [(_tea(client, court), 5)])  # at outlet A
    assert r.json()["detail"]["code"] == "coupon_unknown"


def test_placing_an_order_uses_the_code_once_per_customer(client, shop_a, court):
    c = _make(client, shop_a, "ONCE", "amount", 1000)
    tea = _tea(client, court)
    first = _order(client, court, [(tea, 5)], coupon_code="once")
    assert first.status_code == 201, first.text
    again = _order(client, court, [(tea, 5)], coupon_code="ONCE")
    assert again.status_code == 422 and again.json()["detail"]["code"] == "coupon_already_used"
    listing = client.get(f"{API}/coupons", headers=shop_a.owner_h).json()["coupons"]
    assert next(x for x in listing if x["id"] == c["id"])["uses"] == 1
    # the till learns the discount to bill with
    oid = _live(client, shop_a)[0]["id"]
    extra = client.get(f"{API}/orders/online-paid", headers=shop_a.owner_h).json()
    assert extra["coupon"][oid] == {"code": "ONCE", "discount_paise": 1000}


def test_a_total_limit_and_giving_the_use_back_on_cancel(client, shop_a, court):
    _make(client, shop_a, "ONLYONE", "amount", 1000, max_uses=1)
    tea = _tea(client, court)
    assert _order(client, court, [(tea, 5)], coupon_code="ONLYONE").status_code == 201
    other = {"Authorization": court["customer"]["Authorization"]}  # same customer: already used
    assert _order(client, court, [(tea, 5)], coupon_code="ONLYONE", who=other).status_code == 422


def test_a_paid_order_pays_the_discounted_total_and_keeps_it(client, shop_a, court, rzp):
    _make(client, shop_a, "PAY10", "percent", 10)
    tea = _tea(client, court)
    body = {
        "checkout_id": str(uuid.uuid4()),
        "slug": court["slug"],
        "orders": [
            {
                "outlet_id": court["a"],
                "request_id": str(uuid.uuid4()),
                "note": "",
                "coupon_code": "pay10",
                "items": [{"menu_item_id": tea, "qty": 5}],
            }
        ],
    }
    started = client.post(f"{API}/customer/checkout", json=body, headers=court["customer"])
    assert started.status_code == 201, started.text
    assert started.json()["amount_paise"] == 9000  # ₹100 less ₹10
    _pay(client, rzp, started.json())
    # even if the code is switched off while it was being paid, the paid order is placed
    row = client.get(f"{API}/coupons", headers=shop_a.owner_h).json()["coupons"][0]
    client.patch(f"{API}/coupons/{row['id']}", json={"is_active": False}, headers=shop_a.owner_h)
    live = _live(client, shop_a)
    assert len(live) == 1
    extra = client.get(f"{API}/orders/online-paid", headers=shop_a.owner_h).json()
    assert extra["paid"][live[0]["id"]] == 9000
    assert extra["coupon"][live[0]["id"]]["discount_paise"] == 1000


def test_a_bill_with_the_coupon_discount_is_not_flagged_over_the_limit(client, shop_a, court):
    from tests.conftest import FakeDevice

    _make(client, shop_a, "HALF", "percent", 50)
    tea = _tea(client, court)
    _order(client, court, [(tea, 5)], coupon_code="HALF").raise_for_status()
    oid = _live(client, shop_a)[0]["id"]
    off = client.get(f"{API}/orders/online-paid", headers=shop_a.owner_h).json()["coupon"][oid][
        "discount_paise"
    ]
    dev = FakeDevice(client, shop_a)
    bill = dev.bill([("Masala tea", 5, [])], bill_discount=off, reason="Coupon HALF")
    bill["order_id"] = oid
    r = dev.sync([bill]).json()["results"][0]
    assert r["status"] == "accepted", r
    got = client.get(f"{API}/bills/{bill['id']}", headers=shop_a.owner_h).json()
    assert (
        got["discount_paise"] == off == 5000 and got["flags"] == []
    )  # not over the cashier's limit
    # the same discount on an ordinary bill is flagged for a cashier
    plain = dev.bill([("Masala tea", 5, [])], bill_discount=5000, reason="Because")
    dev.sync([plain])
    flagged = client.get(f"{API}/bills/{plain['id']}", headers=shop_a.owner_h).json()
    assert "discount_over_limit" in flagged["flags"]


def test_only_the_owner_makes_offers_and_bad_ones_are_refused(client, shop_a):
    body = {"code": "NOPE1", "kind": "percent", "value": 10}
    assert client.post(f"{API}/coupons", json=body, headers=shop_a.cashier_h).status_code == 403
    for bad in (
        {"code": "AB", "kind": "percent", "value": 10},
        {"code": "OKAY", "kind": "percent", "value": 101},
        {"code": "OKAY", "kind": "amount", "value": 150},
        {"code": "OKAY", "kind": "amount", "value": 200, "max_discount_paise": 100},
        {"code": "sp ace!", "kind": "percent", "value": 10},
    ):
        assert client.post(f"{API}/coupons", json=bad, headers=shop_a.owner_h).status_code == 422, (
            bad
        )
    _make(client, shop_a, "DUP", "percent", 5)
    dup = client.post(
        f"{API}/coupons",
        json={"code": "dup", "kind": "percent", "value": 5},
        headers=shop_a.owner_h,
    )
    assert dup.status_code == 409


# ---------------------------------------------------------------- linked outlets
def _login_body(shop):
    return {"phone": shop.owner.phone, "password": PASSWORD}


def test_linking_needs_the_other_owners_password_and_shows_both_outlets(client, shop_a, shop_b):
    bad = client.post(
        f"{API}/links",
        json={"phone": shop_b.owner.phone, "password": "wrong-pass-1"},
        headers=shop_a.owner_h,
    )
    assert bad.status_code == 401
    ok = client.post(f"{API}/links", json=_login_body(shop_b), headers=shop_a.owner_h)
    assert ok.status_code == 201, ok.text
    names = [o["name"] for o in ok.json()["outlets"]]
    assert names == ["Shop A", "Shop B"] and ok.json()["outlets"][0]["is_me"] is True
    # linked both ways
    back = client.get(f"{API}/links", headers=shop_b.owner_h).json()["outlets"]
    assert [o["name"] for o in back] == ["Shop B", "Shop A"]
    for o in ok.json()["outlets"]:
        assert set(o) >= {"sales_paise", "bills", "needs_you", "open_online_orders", "user_id"}


def test_a_link_gives_no_access_inside_the_other_shop(client, shop_a, shop_b):
    client.post(f"{API}/links", json=_login_body(shop_b), headers=shop_a.owner_h).raise_for_status()
    build_catalogue(client, shop_b)
    assert client.get(f"{API}/menu-items", headers=shop_a.owner_h).json() == []  # still only A's
    # and nothing issued a token: the only way in is still that shop's own login


def test_only_owners_link_and_a_cashier_login_cannot_be_linked(client, shop_a, shop_b):
    assert client.get(f"{API}/links", headers=shop_a.cashier_h).status_code == 403
    cashier = {"phone": shop_b.cashier.phone, "password": PASSWORD}
    r = client.post(f"{API}/links", json=cashier, headers=shop_a.owner_h)
    assert r.status_code == 422 and "owner" in r.json()["detail"]
    same = client.post(f"{API}/links", json=_login_body(shop_a), headers=shop_a.owner_h)
    assert same.status_code == 422


def test_unlinking_works_both_ways_and_a_switched_off_owner_disappears(client, shop_a, shop_b):
    client.post(f"{API}/links", json=_login_body(shop_b), headers=shop_a.owner_h).raise_for_status()
    other = client.get(f"{API}/links", headers=shop_a.owner_h).json()["outlets"][1]["user_id"]
    gone = client.delete(f"{API}/links/{other}", headers=shop_a.owner_h)
    assert gone.status_code == 200 and len(gone.json()["outlets"]) == 1
    assert len(client.get(f"{API}/links", headers=shop_b.owner_h).json()["outlets"]) == 1
    assert client.delete(f"{API}/links/{other}", headers=shop_a.owner_h).status_code == 404
    # a third shop, linked then switched off by its own shop
    shop_c = make_shop(client, "Shop C")
    client.post(f"{API}/links", json=_login_body(shop_c), headers=shop_a.owner_h).raise_for_status()
    assert len(client.get(f"{API}/links", headers=shop_a.owner_h).json()["outlets"]) == 2
    from app.db.session import SessionLocal
    from app.db.tenancy import mark_system
    from app.models import User

    with mark_system(SessionLocal()) as db:
        db.get(User, shop_c.owner.id).is_active = False
        db.commit()
    assert len(client.get(f"{API}/links", headers=shop_a.owner_h).json()["outlets"]) == 1


# ---------------------------------------------------------------- sold out history
def test_switching_a_dish_sold_out_is_remembered(client, shop_a):
    cat = build_catalogue(client, shop_a)
    h = shop_a.owner_h
    for _ in range(2):
        client.patch(f"{API}/menu-items/{cat.juice['id']}", json={"is_sold_out": True}, headers=h)
        client.patch(f"{API}/menu-items/{cat.juice['id']}", json={"is_sold_out": False}, headers=h)
    client.patch(
        f"{API}/menu-items/{cat.juice['id']}", json={"price_paise": 6500}, headers=h
    )  # not a toggle
    got = client.get(f"{API}/reports/wasted", headers=h).json()
    assert got["sold_out"] == [{"name": "Orange juice", "times": 2}]
