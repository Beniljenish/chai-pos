"""Phase 7: reports over a date range, the monthly GST summary (GSTR-1 shape),
stock valuation, reorder levels, suppliers and purchase orders."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.time import business_date
from tests.conftest import FakeDevice, build_catalogue

API = "/api/v1"


@pytest.fixture
def cat(client, shop_a):
    return build_catalogue(client, shop_a)


@pytest.fixture
def device(client, shop_a, cat):
    return FakeDevice(client, shop_a)


def _accept(device, bill, headers=None):
    r = device.sync([bill], headers=headers).json()["results"][0]
    assert r["status"] == "accepted", r
    return bill


def _stock_in(client, shop, ingredient_id, qty, cost_paise, supplier=""):
    r = client.post(
        f"{API}/stock-in",
        json={
            "ingredient_id": ingredient_id,
            "loose_qty": str(qty),
            "cost_paise": cost_paise,
            "supplier": supplier,
        },
        headers=shop.owner_h,
    )
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------- reports
def test_sales_over_a_date_range(client, shop_a, device):
    now = datetime.now(UTC)
    today, yesterday = business_date(now), business_date(now - timedelta(days=1))
    _accept(device, device.bill([("Masala tea", 2, [])], sold_at=now - timedelta(days=1)))
    _accept(
        device, device.bill([("Masala tea", 1, []), ("Orange juice", 1, [])], payment_mode="upi")
    )
    voided = _accept(device, device.bill([("Orange juice", 3, [])]))
    client.post(
        f"{API}/bills/{voided['id']}/void", json={"reason": "duplicate"}, headers=shop_a.owner_h
    ).raise_for_status()

    q = f"from={yesterday.isoformat()}&to={today.isoformat()}"
    assert client.get(f"{API}/reports/range?{q}", headers=shop_a.cashier_h).status_code == 403
    r = client.get(f"{API}/reports/range?{q}", headers=shop_a.owner_h).json()
    assert r["total_paise"] == 4000 + 8000 and r["bills"] == 2
    assert [(d["business_date"], d["total_paise"]) for d in r["days"]] == [
        (yesterday.isoformat(), 4000),
        (today.isoformat(), 8000),
    ]
    assert {i["name"]: (i["qty"], i["total_paise"]) for i in r["items"]} == {
        "Masala tea": (3, 6000),
        "Orange juice": (1, 6000),
    }
    assert sum(h["total_paise"] for h in r["by_hour"]) == 12000
    assert {m["mode"]: m["total_paise"] for m in r["by_mode"]} == {"cash": 4000, "upi": 8000}
    assert r["voids"] == {"bills": 1, "total_paise": 18000}

    bad = client.get(f"{API}/reports/range?from={today}&to={yesterday}", headers=shop_a.owner_h)
    assert bad.status_code == 422
    far = today - timedelta(days=100)
    assert (
        client.get(f"{API}/reports/range?from={far}&to={today}", headers=shop_a.owner_h).status_code
        == 422
    )


def test_gst_summary_for_a_month_in_gstr1_shape(client, shop_a, device):
    client.patch(
        f"{API}/shop",
        json={"gst_type": "regular", "gstin": "33ABCDE1234F1Z7"},
        headers=shop_a.owner_h,
    ).raise_for_status()
    device.refresh_catalogue()
    a = _accept(device, device.bill([("Masala tea", 2, [])]))
    b = _accept(device, device.bill([("Orange juice", 1, [])]))
    c = _accept(device, device.bill([("Masala tea", 1, [])]))
    client.post(
        f"{API}/bills/{c['id']}/void", json={"reason": "duplicate"}, headers=shop_a.owner_h
    ).raise_for_status()

    month = business_date(datetime.now(UTC)).strftime("%Y-%m")
    assert (
        client.get(f"{API}/reports/gst?month={month}", headers=shop_a.cashier_h).status_code == 403
    )
    r = client.get(f"{API}/reports/gst?month={month}", headers=shop_a.owner_h).json()
    assert r["gst_type"] == "regular" and r["gstin"] == "33ABCDE1234F1Z7"
    # B2C (small): one row per rate, place of supply = the shop's state. The voided bill is out.
    lines = a["lines"] + b["lines"]
    (row,) = r["b2cs"]
    assert row["rate_bp"] == 500 and row["place_of_supply"] == shop_a.shop.state_code
    assert row["taxable_paise"] == sum(ln["totals"]["taxable"] for ln in lines)
    assert row["cgst_paise"] == row["sgst_paise"] == sum(ln["totals"]["cgst"] for ln in lines)
    # HSN summary: tea and juice share the restaurant-service code.
    (hsn,) = r["hsn"]
    assert hsn["hsn_sac"] == "996331" and hsn["qty"] == 3 and hsn["rate_bp"] == 500
    assert hsn["total_paise"] == 4000 + 6000
    # Documents issued: the series, how many, how many cancelled.
    (doc,) = r["documents"]
    assert doc["from"] == a["invoice_no"] and doc["to"] == c["invoice_no"]
    assert (doc["total"], doc["cancelled"], doc["net_issued"]) == (3, 1, 2)
    assert r["totals"]["invoice_value_paise"] == 10000

    assert client.get(f"{API}/reports/gst?month=2026-13", headers=shop_a.owner_h).status_code == 422


def test_stock_valuation(client, shop_a, cat, device):
    _stock_in(client, shop_a, cat.milk["id"], 10000, 6000)  # 0.60 paise per ml
    _stock_in(client, shop_a, cat.sugar["id"], 1000, 5000)
    r = client.get(f"{API}/reports/stock-value", headers=shop_a.owner_h).json()
    rows = {x["name"]: x for x in r["items"]}
    assert rows["Milk"]["value_paise"] == 6000 and rows["Sugar"]["value_paise"] == 5000
    assert r["total_paise"] == sum(x["value_paise"] for x in r["items"])
    assert client.get(f"{API}/reports/stock-value", headers=shop_a.cashier_h).status_code == 403


# ---------------------------------------------------------------- purchasing
def test_a_purchase_order_received_into_stock(client, shop_a, cat):
    h = shop_a.owner_h
    sup = client.post(
        f"{API}/suppliers", json={"name": "Aavin milk agent", "phone": "9000011111"}, headers=h
    ).json()
    assert client.get(f"{API}/suppliers", headers=h).json()[0]["name"] == "Aavin milk agent"
    po = client.post(
        f"{API}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "note": "Monday",
            "lines": [
                {"ingredient_id": cat.milk["id"], "qty": "10000", "expected_cost_paise": 6000},
                {"ingredient_id": cat.sugar["id"], "qty": "2000", "expected_cost_paise": 9000},
            ],
        },
        headers=h,
    )
    assert po.status_code == 201, po.text
    po = po.json()
    assert po["status"] == "open" and po["expected_total_paise"] == 15000
    assert [p["id"] for p in client.get(f"{API}/purchase-orders", headers=h).json()] == [po["id"]]

    milk_line, sugar_line = po["lines"]
    got = client.post(
        f"{API}/purchase-orders/{po['id']}/receive",
        json={
            "lines": [
                # 9 L came, at 54 rupees; the sugar did not come.
                {"line_id": milk_line["id"], "qty": "9000", "cost_paise": 5400},
                {"line_id": sugar_line["id"], "qty": "0", "cost_paise": 0},
            ]
        },
        headers=h,
    )
    assert got.status_code == 200, got.text
    got = got.json()
    assert got["status"] == "received"
    assert [ln["received_qty"] for ln in got["lines"]] == ["9000.000", "0.000"]
    stock = {s["name"]: s for s in client.get(f"{API}/stock", headers=h).json()}
    assert stock["Milk"]["on_hand"] == "9000.000"
    ledger = client.get(f"{API}/stock/{cat.milk['id']}/ledger", headers=h).json()
    assert (ledger[0]["ref_type"], ledger[0]["ref_id"]) == (
        "stock_receipt",
        got["lines"][0]["receipt_id"],
    )
    assert got["lines"][1]["receipt_id"] is None  # nothing came, nothing entered
    # Received once only; and a received order cannot be cancelled.
    again = client.post(f"{API}/purchase-orders/{po['id']}/receive", json={"lines": []}, headers=h)
    assert again.status_code == 409
    assert client.post(f"{API}/purchase-orders/{po['id']}/cancel", headers=h).status_code == 409
    # Cashiers do not buy for the shop.
    assert client.get(f"{API}/purchase-orders", headers=shop_a.cashier_h).status_code == 403


def test_an_open_order_can_be_cancelled(client, shop_a, cat):
    h = shop_a.owner_h
    sup = client.post(f"{API}/suppliers", json={"name": "Sugar shop"}, headers=h).json()
    po = client.post(
        f"{API}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "lines": [{"ingredient_id": cat.sugar["id"], "qty": "1000"}],
        },
        headers=h,
    ).json()
    r = client.post(f"{API}/purchase-orders/{po['id']}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_suggested_order_from_reorder_levels(client, shop_a, cat):
    h = shop_a.owner_h
    client.patch(f"{API}/ingredients/{cat.milk['id']}", json={"reorder_level": "5000"}, headers=h)
    client.patch(f"{API}/ingredients/{cat.sugar['id']}", json={"reorder_level": "500"}, headers=h)
    _stock_in(client, shop_a, cat.milk["id"], 2000, 1200)
    _stock_in(client, shop_a, cat.sugar["id"], 3000, 1500)  # plenty
    r = client.get(f"{API}/purchase-orders/suggest", headers=h).json()
    # Below its level: bring it up to twice the level (2000 -> 10000).
    assert r["lines"] == [
        {
            "ingredient_id": cat.milk["id"],
            "name": "Milk",
            "base_unit": "ml",
            "on_hand": "2000.000",
            "reorder_level": "5000.000",
            "qty": "8000.000",
            "expected_cost_paise": 4800,
        }
    ]
