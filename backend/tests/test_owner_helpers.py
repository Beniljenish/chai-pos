# ruff: noqa: F811  (fixtures imported from other test modules are used as arguments)
"""The owner's helpers (README, "9.17"): dishes that sell out by themselves when the stock is
gone, what to prepare today, and the end-of-day message."""

import uuid
from datetime import timedelta
from decimal import Decimal

from app.core.time import business_date, utcnow
from app.models import LedgerReason, StockLedger
from app.services import messages, online, summary
from tests.conftest import build_catalogue
from tests.test_food_court import API, _menu, _order, court  # noqa: F401


def _count(client, shop, ingredient_id, grams):
    client.post(
        f"{API}/stock/opening",
        json={"ingredient_id": ingredient_id, "loose_qty": str(grams)},
        headers=shop.owner_h,
    ).raise_for_status()


def test_a_dish_sells_out_when_the_counted_stock_cannot_make_one(client, shop_a, court):
    oranges = client.get(f"{API}/ingredients", headers=shop_a.owner_h).json()
    oranges = next(i for i in oranges if i["name"] == "Oranges")["id"]
    _count(client, shop_a, oranges, 100)  # a portion needs about 555 g

    # off: nothing changes, whatever the stock says
    assert _menu(client, court)["Orange juice"]["sold_out"] is False

    client.patch(
        f"{API}/shop", json={"auto_sold_out": True}, headers=shop_a.owner_h
    ).raise_for_status()
    menu = _menu(client, court)
    assert menu["Orange juice"]["sold_out"] is True
    # made in the shop (decoction) and never counted dishes are not judged by the shelf
    assert menu["Masala tea"]["sold_out"] is False
    refused = _order(client, court, [(menu["Orange juice"]["id"], 1)])
    assert refused.status_code == 409

    # stock arrives: it is orderable again with no one touching a switch
    _count_more = client.get(f"{API}/ingredients", headers=shop_a.owner_h).json()
    assert _count_more  # the count itself is once-only, so receive stock instead
    pack = next(i for i in _count_more if i["name"] == "Oranges")
    client.post(
        f"{API}/stock-in",
        json={"ingredient_id": pack["id"], "packs": [], "loose_qty": "5000", "cost_paise": 40000},
        headers=shop_a.owner_h,
    ).raise_for_status()
    assert _menu(client, court)["Orange juice"]["sold_out"] is False


def test_never_counted_stock_does_not_sell_a_dish_out(client, shop_a, court):
    client.patch(f"{API}/shop", json={"auto_sold_out": True}, headers=shop_a.owner_h)
    assert _menu(client, court)["Orange juice"]["sold_out"] is False  # no opening count: unknown


def test_tomorrows_prep_is_the_average_use_on_the_same_weekday(client, shop_a):
    cat = build_catalogue(client, shop_a)
    tomorrow = business_date(utcnow()) + timedelta(days=1)

    def use(ingredient_id, day, qty, reason=LedgerReason.sale):
        db.add(
            StockLedger(
                ingredient_id=uuid.UUID(ingredient_id),
                qty_delta=-Decimal(qty),
                reason=reason,
                ref_type="test",
                ref_id=uuid.uuid4(),
                business_date=day,
                created_by=shop_a.owner.id,
            )
        )

    with online.shop_session(shop_a.shop.id) as db:
        for weeks, milk in ((1, 16000), (2, 18000), (3, 20000), (4, 18000)):
            use(cat.milk["id"], tomorrow - timedelta(days=7 * weeks), milk, LedgerReason.prep_out)
        use(cat.milk["id"], tomorrow - timedelta(days=8), 99999)  # another weekday: not counted
        use(cat.decoction["id"], tomorrow - timedelta(days=7), 5000)  # made in shop: never listed
        db.commit()
    got = client.get(f"{API}/stock/tomorrow", headers=shop_a.owner_h).json()
    assert got["weekday"] == tomorrow.strftime("%A")
    assert [(i["name"], Decimal(i["qty"]), i["base_unit"]) for i in got["items"]] == [
        ("Milk", Decimal(18000), "ml")
    ]
    # it is about stock, so a cashier does not get it
    assert client.get(f"{API}/stock/tomorrow", headers=shop_a.cashier_h).status_code == 403


def test_the_summary_message_is_short_and_goes_to_the_owner_number(client, shop_a):
    build_catalogue(client, shop_a)
    r = client.patch(
        f"{API}/shop",
        json={"summary_phone": "+91 90000 12345", "summary_on": True},
        headers=shop_a.owner_h,
    )
    assert r.status_code == 200 and r.json()["summary_phone"] == "9000012345"
    sent = []
    messages.set_transport(lambda to, text, key: sent.append((to, text, key)) or "id1")
    try:
        with online.shop_session(shop_a.shop.id) as db:
            shop = db.get(type(shop_a.shop), shop_a.shop.id)
            text = summary.text_for(db, shop, business_date(utcnow()))
            assert summary.send(db, shop, business_date(utcnow())) == "sent"
    finally:
        messages.set_transport(None)
    assert text.startswith("Shop A · ") and "Sales ₹0 from 0 bills" in text
    assert sent[0][0] == "+919000012345" and sent[0][1] == text
    # off, or no number: nothing goes out
    client.patch(f"{API}/shop", json={"summary_on": False}, headers=shop_a.owner_h)
    with online.shop_session(shop_a.shop.id) as db:
        assert summary.send(db, db.get(type(shop_a.shop), shop_a.shop.id), utcnow().date()) == "off"


def test_the_test_button_needs_a_number_and_a_cashier_cannot_use_it(client, shop_a):
    assert client.post(f"{API}/shop/summary/test", headers=shop_a.cashier_h).status_code == 403
    assert client.post(f"{API}/shop/summary/test", headers=shop_a.owner_h).status_code == 422
    client.patch(f"{API}/shop", json={"summary_phone": "9000012345"}, headers=shop_a.owner_h)
    r = client.post(f"{API}/shop/summary/test", headers=shop_a.owner_h).json()
    assert r["status"] == "logged" and r["text"].startswith("Shop A")
    uuid.UUID(str(shop_a.shop.id))  # (fixture sanity)
