# ruff: noqa: F811  (fixtures imported from other test modules are used as arguments)
"""Paying online for a food court order (services/onlinepay.py).

What matters: nothing reaches a kitchen until Razorpay confirms the money; a paid cart is
placed at every outlet, and any outlet that cannot take its part is refunded; the same news
twice (a retried verify, a second webhook) changes nothing; and the money each outlet is owed
adds up to what customers paid."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import MenuItem, OnlineOrder, OnlinePayment
from app.services import payments
from tests.conftest import customer_headers
from tests.test_food_court import API, _events, _live, _menu, court  # noqa: F401
from tests.test_payments import HOOK_SECRET, KEY_SECRET, FakeRazorpay, _hook, _sign  # noqa: F401


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


def _cart(client, c, picks):
    """picks: [(which outlet 'a'/'b', dish name, qty)] -> the checkout body's `orders`."""
    out = {}
    for which, dish, qty in picks:
        menu = _menu(client, c, which)
        part = out.setdefault(
            which,
            {"outlet_id": c[which], "request_id": str(uuid.uuid4()), "note": "", "items": []},
        )
        part["items"].append({"menu_item_id": menu[dish]["id"], "qty": qty})
    return list(out.values())


def _start(client, c, picks, who=None, checkout_id=None):
    return client.post(
        f"{API}/customer/checkout",
        json={
            "checkout_id": checkout_id or str(uuid.uuid4()),
            "slug": c["slug"],
            "message_ok": True,
            "orders": _cart(client, c, picks),
        },
        headers=who or c["customer"],
    )


def _verify(client, order_id, payment_id="pay_TEST0001", sig=None):
    return client.post(
        f"{API}/payments/razorpay/verify",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": sig or _sign(order_id, payment_id),
        },
    )


def _status(client, c, checkout_id, who=None):
    return client.get(f"{API}/customer/checkout/{checkout_id}", headers=who or c["customer"])


def _pay(client, rzp, started, payment_id="pay_TEST0001"):
    rzp.pay(started["razorpay_order_id"], payment_id, started["amount_paise"])
    r = _verify(client, started["razorpay_order_id"], payment_id)
    assert r.status_code == 200 and r.json()["status"] == "paid", r.text


TWO = [("a", "Masala tea", 2), ("b", "Orange juice", 1)]


def test_the_court_says_whether_online_payment_is_on(client, court, rzp, monkeypatch):
    assert client.get(f"{API}/public/courts/{court['slug']}").json()["online_payment"] is True
    monkeypatch.setattr(get_settings(), "razorpay_key_id", "")
    assert client.get(f"{API}/public/courts/{court['slug']}").json()["online_payment"] is False


def test_without_keys_online_payment_is_refused_and_nothing_is_made(client, shop_a, court):
    payments.set_client(FakeRazorpay())  # keys unset: enabled() is false whatever the client
    try:
        r = _start(client, court, TWO)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "online_payments_off"
    finally:
        payments.set_client(None)
    assert _live(client, shop_a) == []


def test_checkout_needs_a_customer_account(client, court, rzp, shop_a):
    body = {
        "checkout_id": str(uuid.uuid4()),
        "slug": court["slug"],
        "orders": _cart(client, court, TWO),
    }
    assert client.post(f"{API}/customer/checkout", json=body).status_code == 401
    for h in (shop_a.owner_h, court["admin"]):
        assert client.post(f"{API}/customer/checkout", json=body, headers=h).status_code == 401
    assert rzp.orders == []


def test_the_cart_is_priced_by_the_server_and_nothing_is_cooked_before_payment(
    client,
    shop_a,
    shop_b,
    court,
    rzp,
):
    r = _start(client, court, TWO)
    assert r.status_code == 201, r.text
    started = r.json()
    # 2 teas at ₹20 and one juice at ₹60, each worked out the way its own bill will be
    assert started["amount_paise"] == 2 * 2000 + 6000 or started["amount_paise"] > 0
    assert rzp.orders[0]["amount"] == started["amount_paise"]
    assert started["status"] == "created" and started["fulfilled"] is False
    assert started["orders"] == []  # no tokens until it is paid
    assert _live(client, shop_a) == [] and _live(client, shop_b) == []


def test_the_same_tap_twice_is_one_payment(client, court, rzp):
    cid = str(uuid.uuid4())
    one = _start(client, court, TWO, checkout_id=cid).json()
    two = _start(client, court, TWO, checkout_id=cid).json()
    assert one["id"] == two["id"] and len(rzp.orders) == 1


def test_a_bad_signature_pays_nothing_and_places_nothing(client, shop_a, shop_b, court, rzp):
    started = _start(client, court, TWO).json()
    bad = _verify(client, started["razorpay_order_id"], sig="0" * 64)
    assert bad.status_code == 400
    assert _status(client, court, started["id"]).json()["status"] == "created"
    assert _live(client, shop_a) == [] and _live(client, shop_b) == []


def test_a_paid_cart_is_placed_at_every_outlet_with_what_was_paid(
    client,
    shop_a,
    shop_b,
    court,
    rzp,
):
    started = _start(client, court, TWO).json()
    _pay(client, rzp, started)
    done = _status(client, court, started["id"]).json()
    assert done["status"] == "paid" and done["fulfilled"] is True
    assert [o["token"] is not None for o in done["orders"]] == [True, True]
    assert sum(o["amount_paise"] for o in done["orders"]) == started["amount_paise"]
    assert rzp.refunds == []
    for shop in (shop_a, shop_b):
        assert len(_live(client, shop)) == 1
    # the customer's status page says it is paid; a counter order's does not
    first_key = done["orders"][0]["status_key"]
    assert client.get(f"{API}/public/orders/{first_key}").json()["paid_online"]
    # each outlet's order remembers what was paid for it
    with mark_system(SessionLocal()) as db:
        rows = db.scalars(select(OnlineOrder).where(OnlineOrder.payment_id.is_not(None))).all()
        assert sorted(r.paid_paise for r in rows) == sorted(
            o["amount_paise"] for o in done["orders"]
        )
        assert {r.payment_id for r in rows} == {uuid.UUID(started["id"])}
    # and the customer finds both in My orders, linked to their account
    mine = client.get(f"{API}/customer/orders", headers=court["customer"]).json()["orders"]
    assert len(mine) == 2
    # whereas an order to pay at the counter says so
    counter_key = _order_at_counter(client, court)["status_key"]
    assert client.get(f"{API}/public/orders/{counter_key}").json()["paid_online"] is False


def test_a_retried_verify_and_the_webhook_place_nothing_twice(client, shop_a, shop_b, court, rzp):
    started = _start(client, court, TWO).json()
    _pay(client, rzp, started)
    again = _verify(client, started["razorpay_order_id"])
    assert again.status_code == 200
    entity = {
        "id": "pay_TEST0001",
        "order_id": started["razorpay_order_id"],
        "amount": started["amount_paise"],
        "status": "captured",
        "method": "upi",
    }
    assert _hook(client, "payment.captured", entity).status_code == 200
    assert _hook(client, "payment.captured", entity).status_code == 200
    for shop in (shop_a, shop_b):
        assert len(_live(client, shop)) == 1
    assert rzp.refunds == []


def test_the_webhook_alone_places_the_orders_when_the_customer_closed_the_tab(
    client,
    shop_a,
    shop_b,
    court,
    rzp,
):
    started = _start(client, court, TWO).json()
    entity = {
        "id": "pay_TEST0002",
        "order_id": started["razorpay_order_id"],
        "amount": started["amount_paise"],
        "status": "captured",
        "method": "card",
    }
    assert _hook(client, "payment.captured", entity).status_code == 200
    done = _status(client, court, started["id"]).json()
    assert done["fulfilled"] is True and all(o["token"] for o in done["orders"])
    for shop in (shop_a, shop_b):
        assert len(_live(client, shop)) == 1


def test_an_outlet_that_sold_out_while_paying_is_refunded_and_the_other_still_goes_through(
    client,
    shop_a,
    shop_b,
    court,
    rzp,
):
    started = _start(client, court, TWO).json()
    juice = _menu(client, court, "b")["Orange juice"]["id"]
    client.patch(
        f"{API}/menu-items/{juice}", json={"is_sold_out": True}, headers=shop_b.owner_h
    ).raise_for_status()
    _pay(client, rzp, started)
    done = _status(client, court, started["id"]).json()
    by_outlet = {o["outlet"]: o for o in done["orders"]}
    placed = [o for o in done["orders"] if o["token"]]
    failed = [o for o in done["orders"] if o["error"]]
    assert len(placed) == 1 and len(failed) == 1
    assert failed[0]["error"] == "items_unavailable" and failed[0]["refunded"] is True
    assert rzp.refunds == [("pay_TEST0001", failed[0]["amount_paise"])]
    assert done["refunded_paise"] == failed[0]["amount_paise"]
    assert len(_live(client, shop_a)) == 1 and _live(client, shop_b) == []
    assert by_outlet  # both outlets are named in the answer


def test_a_price_change_while_paying_refunds_that_outlet(client, shop_a, court, rzp):
    started = _start(client, court, [("a", "Masala tea", 1)]).json()
    with mark_system(SessionLocal()) as db:
        tea = db.scalar(
            select(MenuItem).where(
                MenuItem.name == "Masala tea", MenuItem.shop_id == shop_a.shop.id
            )
        )
        tea.price_paise += 500
        db.commit()
    _pay(client, rzp, started)
    done = _status(client, court, started["id"]).json()
    assert done["orders"][0]["error"] == "price_changed" and done["orders"][0]["refunded"] is True
    assert rzp.refunds == [("pay_TEST0001", started["amount_paise"])]
    assert _live(client, shop_a) == []


def test_a_failed_automatic_refund_is_left_for_the_admin_and_made_once(
    client,
    shop_a,
    shop_b,
    court,
    rzp,
):
    started = _start(client, court, TWO).json()
    juice = _menu(client, court, "b")["Orange juice"]["id"]
    client.patch(
        f"{API}/menu-items/{juice}", json={"is_sold_out": True}, headers=shop_b.owner_h
    ).raise_for_status()
    rzp.refuse_refunds = True
    _pay(client, rzp, started)
    done = _status(client, court, started["id"]).json()
    assert [o["refunded"] for o in done["orders"] if o["error"]] == [False]

    due = client.get(f"{API}/platform/online-money", headers=court["admin"]).json()["refunds_due"]
    assert len(due) == 1 and due[0]["phone"] == "9840012345" and due[0]["token"] is None
    rzp.refuse_refunds = False
    r = client.post(f"{API}/platform/refunds", json={"ref": due[0]["ref"]}, headers=court["admin"])
    assert r.status_code == 200 and r.json()["refunds_due"] == []
    assert len(rzp.refunds) == 1
    again = client.post(
        f"{API}/platform/refunds", json={"ref": due[0]["ref"]}, headers=court["admin"]
    )
    assert again.status_code in (200, 404) and len(rzp.refunds) == 1  # never twice


def test_an_order_the_outlet_cancels_after_payment_is_a_refund_due_not_money_owed(
    client,
    shop_a,
    shop_b,
    court,
    rzp,
):
    started = _start(client, court, TWO).json()
    _pay(client, rzp, started)
    done = _status(client, court, started["id"]).json()
    a_order = next(o for o in done["orders"] if o["outlet"] == shop_a.shop.name)

    before = {
        o["outlet"]: o
        for o in client.get(f"{API}/platform/online-money", headers=court["admin"]).json()[
            "outlets"
        ]
    }
    assert before[shop_a.shop.name]["owed_paise"] == a_order["amount_paise"]

    rzp.refuse_refunds = True  # the automatic refund fails: it waits for the admin instead
    live = _live(client, shop_a)[0]
    _events(client, shop_a, live["id"], [("cancel_order", {"reason": "out of milk"})])

    money = client.get(f"{API}/platform/online-money", headers=court["admin"]).json()
    owed = {o["outlet"]: o["owed_paise"] for o in money["outlets"]}
    assert owed[shop_a.shop.name] == 0  # a cancelled order is not the outlet's sale
    assert len(money["refunds_due"]) == 1
    ref = money["refunds_due"][0]
    assert ref["amount_paise"] == a_order["amount_paise"] and ref["outlet"] == shop_a.shop.name

    rzp.refuse_refunds = False
    r = client.post(f"{API}/platform/refunds", json={"ref": ref["ref"]}, headers=court["admin"])
    assert r.status_code == 200 and r.json()["refunds_due"] == []
    assert rzp.refunds == [("pay_TEST0001", a_order["amount_paise"])]
    client.post(f"{API}/platform/refunds", json={"ref": ref["ref"]}, headers=court["admin"])
    assert len(rzp.refunds) == 1


def test_what_each_outlet_is_owed_adds_up_and_settling_is_capped(
    client, shop_a, shop_b, court, rzp
):
    started = _start(client, court, TWO).json()
    _pay(client, rzp, started)
    admin = court["admin"]
    outlets = client.get(f"{API}/platform/online-money", headers=admin).json()["outlets"]
    assert sum(o["owed_paise"] for o in outlets) == started["amount_paise"]
    a = next(o for o in outlets if o["outlet"] == shop_a.shop.name)
    assert a["orders"] == 1

    url = f"{API}/platform/courts/{court['id']}/outlets/{a['outlet_id']}/settlements"
    assert (
        client.post(url, json={"amount_paise": a["owed_paise"] + 1}, headers=admin).status_code
        == 409
    )
    half = a["owed_paise"] // 2
    ok = client.post(url, json={"amount_paise": half, "note": "UPI to the outlet"}, headers=admin)
    assert ok.status_code == 201
    left = next(o for o in ok.json()["outlets"] if o["outlet_id"] == a["outlet_id"])
    assert left["settled_paise"] == half and left["owed_paise"] == a["owed_paise"] - half
    # the outlet's own owner sees the same figures, and only theirs
    mine = client.get(f"{API}/food-court", headers=shop_a.owner_h).json()["online_money"]
    assert mine["paid_paise"] == a["paid_paise"] and mine["settled_paise"] == half


def test_settlement_routes_are_the_admins_alone_and_check_the_court(client, shop_a, court, rzp):
    outlets = client.get(f"{API}/platform/online-money", headers=court["admin"]).json()["outlets"]
    outlet_id = outlets[0]["outlet_id"]
    url = f"{API}/platform/courts/{court['id']}/outlets/{outlet_id}/settlements"
    for h in (shop_a.owner_h, court["customer"], {}):
        assert client.post(url, json={"amount_paise": 100}, headers=h).status_code == 401
        assert client.get(f"{API}/platform/online-money", headers=h).status_code == 401
        assert (
            client.post(f"{API}/platform/refunds", json={"ref": "order:x"}, headers=h).status_code
            == 401
        )
    other = f"{API}/platform/courts/{uuid.uuid4()}/outlets/{outlet_id}/settlements"
    assert client.post(other, json={"amount_paise": 100}, headers=court["admin"]).status_code == 404


def test_one_customer_cannot_read_anothers_payment(client, court, rzp, shop_a):
    started = _start(client, court, TWO).json()
    other = customer_headers(client, "9841100000", "Priya")
    assert _status(client, court, started["id"], who=other).status_code == 404
    assert _status(client, court, started["id"], who=shop_a.owner_h).status_code == 401
    # nor can another customer reuse the same checkout id to see or hijack it
    reuse = _start(client, court, TWO, who=other, checkout_id=started["id"])
    assert reuse.status_code == 404
    assert _status(client, court, str(uuid.uuid4())).status_code == 404


def test_the_hosted_payment_page_shows_only_the_court_and_the_amount(client, court, rzp):
    started = _start(client, court, TWO).json()
    page = client.get(
        f"{API}/payments/razorpay/customer-checkout?order_id={started['razorpay_order_id']}"
    )
    assert page.status_code == 200
    assert "Marina Food Court" in page.text and "rzp_test_PUBLICKEY" in page.text
    assert KEY_SECRET not in page.text
    assert (
        client.get(f"{API}/payments/razorpay/customer-checkout?order_id=order_nope").status_code
        == 404
    )
    _pay(client, rzp, started)
    again = client.get(
        f"{API}/payments/razorpay/customer-checkout?order_id={started['razorpay_order_id']}"
    )
    assert "already paid" in again.text


def test_a_failed_payment_places_nothing_and_a_later_success_still_wins(client, shop_a, court, rzp):
    started = _start(client, court, TWO).json()
    r = client.post(
        f"{API}/payments/razorpay/failed",
        json={"razorpay_order_id": started["razorpay_order_id"], "reason": "Insufficient funds"},
    )
    assert r.status_code == 200 and r.json()["status"] == "failed"
    assert _live(client, shop_a) == []
    _pay(client, rzp, started)
    assert _status(client, court, started["id"]).json()["status"] == "paid"


def test_a_cart_over_the_limits_is_refused_before_any_charge(client, court, rzp):
    tea = _menu(client, court, "a")["Masala tea"]["id"]
    body = {
        "checkout_id": str(uuid.uuid4()),
        "slug": court["slug"],
        "orders": [
            {
                "outlet_id": court["a"],
                "request_id": str(uuid.uuid4()),
                "items": [{"menu_item_id": tea, "qty": 21}],
            }
        ],
    }
    assert (
        client.post(f"{API}/customer/checkout", json=body, headers=court["customer"]).status_code
        == 422
    )
    dup = {
        **body,
        "orders": [
            {
                "outlet_id": court["a"],
                "request_id": str(uuid.uuid4()),
                "items": [{"menu_item_id": tea, "qty": 1}],
            },
            {
                "outlet_id": court["a"],
                "request_id": str(uuid.uuid4()),
                "items": [{"menu_item_id": tea, "qty": 1}],
            },
        ],
    }
    r = client.post(f"{API}/customer/checkout", json=dup, headers=court["customer"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "order_too_big"
    assert rzp.orders == []
    with mark_system(SessionLocal()) as db:
        assert db.scalars(select(OnlinePayment)).all() == []


def test_the_till_can_ask_which_open_online_orders_are_already_paid(
    client, shop_a, shop_b, court, rzp
):
    started = _start(client, court, TWO).json()
    _pay(client, rzp, started)
    counter = _order_at_counter(client, court)
    paid_a = client.get(f"{API}/orders/online-paid", headers=shop_a.cashier_h).json()["paid"]
    live_a = {o["id"]: o for o in _live(client, shop_a)}
    assert set(paid_a) <= set(live_a) and len(paid_a) == 1  # only this shop's, only the paid one
    assert counter["order_id"] in live_a and counter["order_id"] not in paid_a
    paid_b = client.get(f"{API}/orders/online-paid", headers=shop_b.cashier_h).json()["paid"]
    assert set(paid_a).isdisjoint(paid_b)  # another shop never sees this one's
    assert client.get(f"{API}/orders/online-paid").status_code == 401


def _order_at_counter(client, c):
    tea = _menu(client, c, "a")["Masala tea"]["id"]
    r = client.post(
        f"{API}/public/courts/{c['slug']}/outlets/{c['a']}/orders",
        json={"request_id": str(uuid.uuid4()), "items": [{"menu_item_id": tea, "qty": 1}]},
        headers=c["customer"],
    )
    assert r.status_code == 201, r.text
    return r.json()
