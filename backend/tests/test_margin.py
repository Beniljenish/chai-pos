"""What each item costs to make and keeps: from the current recipe and the latest
price paid for each ingredient (services/margin.py)."""

import pytest

from tests.conftest import build_catalogue
from tests.test_phase7 import _stock_in

API = "/api/v1"


@pytest.fixture
def cat(client, shop_a):
    return build_catalogue(client, shop_a)


def _items(client, shop):
    r = client.get(f"{API}/reports/margin", headers=shop.owner_h)
    assert r.status_code == 200, r.text
    return {i["name"]: i for i in r.json()["items"]}


def test_owner_only(client, shop_a, cat):
    assert client.get(f"{API}/reports/margin", headers=shop_a.cashier_h).status_code == 403


def test_no_prices_means_no_margin_not_a_full_margin(client, shop_a, cat):
    items = _items(client, shop_a)
    tea = items["Masala tea"]
    assert tea["status"] == "incomplete"
    assert tea["margin_pct"] is None and tea["cost_paise"] is None
    assert tea["missing"] == ["Milk", "Sugar", "Tea powder"]


def test_made_here_ingredient_costs_its_inputs_over_the_yield(client, shop_a, cat):
    # 6 paise/ml milk, 5 paise/g sugar, 40 paise/g tea powder
    _stock_in(client, shop_a, cat.milk["id"], 10000, 60000)
    _stock_in(client, shop_a, cat.sugar["id"], 1000, 5000)
    _stock_in(client, shop_a, cat.tea_powder["id"], 250, 10000)
    tea = _items(client, shop_a)["Masala tea"]
    # decoction: 2000*6 + 60*40 + 150*5 = 15150 paise over 2200 ml; the tea uses 100 ml
    assert tea["cost_paise"] == 689  # 688.64, rounded half up once at the end
    assert tea["net_paise"] == 1904  # the test shop is GST-registered: 19.04 + 0.48 + 0.48
    assert tea["margin_paise"] == 1904 - 689
    assert tea["margin_pct"] == 64  # 1215 / 1904 = 63.8%
    assert tea["status"] == "ok"


def test_an_unregistered_shop_keeps_the_whole_price_as_revenue(client, shop_a, cat):
    client.patch(
        f"{API}/shop", json={"gst_type": "unregistered"}, headers=shop_a.owner_h
    ).raise_for_status()
    _stock_in(client, shop_a, cat.milk["id"], 10000, 60000)
    _stock_in(client, shop_a, cat.sugar["id"], 1000, 5000)
    _stock_in(client, shop_a, cat.tea_powder["id"], 250, 10000)
    tea = _items(client, shop_a)["Masala tea"]
    assert tea["net_paise"] == 2000  # no GST charged, so nothing to take out
    assert tea["margin_paise"] == 2000 - 689
    assert tea["margin_pct"] == 66


def test_items_that_cannot_be_costed_come_last_and_say_why(client, shop_a, cat):
    _stock_in(client, shop_a, cat.milk["id"], 10000, 60000)
    _stock_in(client, shop_a, cat.sugar["id"], 1000, 5000)
    _stock_in(client, shop_a, cat.tea_powder["id"], 250, 10000)
    r = client.get(f"{API}/reports/margin", headers=shop_a.owner_h).json()["items"]
    assert [i["name"] for i in r] == ["Masala tea", "Orange juice"]
    juice = r[1]
    assert juice["status"] == "incomplete" and juice["missing"] == ["Oranges"]
