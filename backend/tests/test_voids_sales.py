"""Voids and the daily sales report.

A void never edits or deletes the bill: it adds a BillVoid, flips the status,
and (unless the drink was made) returns exactly the stock that bill took.
"""

from decimal import Decimal

import pytest

from app.core.time import business_date, utcnow
from tests.conftest import FakeDevice, build_catalogue

D = Decimal


@pytest.fixture
def cat(client, shop_a):
    c = build_catalogue(client, shop_a)
    large = client.post(
        "/api/v1/modifiers",
        json={"name": "Large", "price_delta_paise": 1000, "scale_factor": "1.5"},
        headers=shop_a.owner_h,
    ).json()
    client.put(
        f"/api/v1/modifiers/{large['id']}/menu-items",
        json={"menu_item_ids": [c.tea["id"]]},
        headers=shop_a.owner_h,
    ).raise_for_status()
    return c


@pytest.fixture
def device(client, shop_a, cat):
    return FakeDevice(client, shop_a)


def _sell(device, items, **kw) -> str:
    bill = device.bill(items, **kw)
    r = device.sync([bill])
    assert r.status_code == 200 and r.json()["results"][0]["status"] == "accepted", r.text
    return bill["id"]


def _ledger(client, h, ingredient_id):
    return client.get(f"/api/v1/stock/{ingredient_id}/ledger", headers=h).json()


def _on_hand(client, h, name) -> D:
    rows = {r["name"]: r for r in client.get("/api/v1/stock", headers=h).json()}
    return D(rows[name]["on_hand"])


def _void(client, h, bill_id, **body):
    return client.post(
        f"/api/v1/bills/{bill_id}/void", json={"reason": "wrong_item", **body}, headers=h
    )


def test_void_returns_exactly_the_stock_the_bill_took(client, shop_a, cat, device):
    h = shop_a.owner_h
    keep = _sell(device, [("Masala tea", 1, [])])
    wrong = _sell(device, [("Masala tea", 2, ["Large"])])  # 2 x 150 ml decoction
    assert _on_hand(client, h, "Tea decoction") == D("-400")

    r = _void(client, h, wrong, note="tapped Large by mistake")
    assert r.status_code == 200, r.text
    bill = r.json()
    assert bill["status"] == "void"
    assert bill["void"]["reason"] == "wrong_item"
    assert bill["void"]["stock_returned"] is True
    assert bill["void"]["note"] == "tapped Large by mistake"
    assert bill["void"]["voided_by_name"]

    assert _on_hand(client, h, "Tea decoction") == D("-100")  # only the kept tea
    rows = _ledger(client, h, cat.decoction["id"])
    assert sorted((x["reason"], D(x["qty_delta"])) for x in rows) == [
        ("sale", D(-300)),
        ("sale", D(-100)),
        ("void", D(300)),
    ]
    # The bill itself is untouched apart from its status; its number stays used.
    one = client.get(f"/api/v1/bills/{wrong}", headers=h).json()
    assert one["total_paise"] == 6000 and one["invoice_no"].endswith("000002")
    assert client.get(f"/api/v1/bills/{keep}", headers=h).json()["void"] is None


def test_drink_already_made_keeps_the_stock_out(client, shop_a, cat, device):
    h = shop_a.owner_h
    bill_id = _sell(device, [("Masala tea", 1, [])])
    r = _void(client, h, bill_id, reason="customer_cancelled", drink_was_made=True)
    assert r.status_code == 200
    assert r.json()["void"]["stock_returned"] is False
    assert _on_hand(client, h, "Tea decoction") == D("-100")
    assert [x["reason"] for x in _ledger(client, h, cat.decoction["id"])] == ["sale"]


def test_only_the_owner_voids_and_only_once(client, shop_a, cat, device):
    bill_id = _sell(device, [("Masala tea", 1, [])])
    assert _void(client, shop_a.cashier_h, bill_id).status_code == 403
    assert _void(client, shop_a.owner_h, bill_id).status_code == 200
    again = _void(client, shop_a.owner_h, bill_id)
    assert again.status_code == 409 and "already" in again.json()["detail"]
    # Exactly one reversal, however many times it is asked for.
    rows = _ledger(client, shop_a.owner_h, cat.decoction["id"])
    assert [x["reason"] for x in rows].count("void") == 1
    assert _void(client, shop_a.owner_h, "00000000-0000-0000-0000-000000000000").status_code == 404
    bad = client.post(
        f"/api/v1/bills/{bill_id}/void", json={"reason": "felt like it"}, headers=shop_a.owner_h
    )
    assert bad.status_code == 422


def test_a_resent_bill_stays_voided(client, shop_a, cat, device):
    """The tablet may retry a sync it never heard back from, after the void."""
    bill = device.bill([("Masala tea", 1, [])])
    device.sync([bill]).raise_for_status()
    _void(client, shop_a.owner_h, bill["id"]).raise_for_status()
    r = device.sync([bill])
    assert r.json()["results"][0]["status"] == "duplicate"
    assert client.get(f"/api/v1/bills/{bill['id']}", headers=shop_a.owner_h).json()["status"] == (
        "void"
    )
    assert _on_hand(client, shop_a.owner_h, "Tea decoction") == D("0")


def test_no_voids_once_the_day_is_closed(client, shop_a, cat, device):
    h = shop_a.owner_h
    bill_id = _sell(device, [("Masala tea", 1, [])])
    day = business_date(utcnow()).isoformat()
    client.post(
        f"/api/v1/day-counts/{day}/counts",
        json={"lines": [{"ingredient_id": cat.decoction["id"], "loose_qty": "0"}]},
        headers=h,
    ).raise_for_status()
    assert client.post(f"/api/v1/day-counts/{day}/approve", headers=h).status_code == 200
    r = _void(client, h, bill_id)
    assert r.status_code == 409 and "closed" in r.json()["detail"]
    assert client.get(f"/api/v1/bills/{bill_id}", headers=h).json()["status"] == "completed"


def test_voids_net_out_of_the_days_sold_figure(client, shop_a, cat, device):
    """Day end: a voided (not made) drink is not usage, so it must not raise the
    expected usage the count is judged against."""
    h = shop_a.owner_h
    _sell(device, [("Masala tea", 3, [])])
    wrong = _sell(device, [("Masala tea", 1, [])])
    _void(client, h, wrong).raise_for_status()
    day = business_date(utcnow()).isoformat()
    sheet = client.get(f"/api/v1/day-counts/{day}/sheet", headers=h).json()
    dec = next(i for i in sheet["items"] if i["ingredient_id"] == cat.decoction["id"])
    assert D(dec["expected"]) == D("-300")
    client.post(
        f"/api/v1/day-counts/{day}/counts",
        json={"lines": [{"ingredient_id": cat.decoction["id"], "loose_qty": "0"}]},
        headers=h,
    ).raise_for_status()
    rep = client.get(f"/api/v1/day-counts/{day}/report", headers=h).json()
    line = next(x for x in rep["lines"] if x["ingredient_id"] == cat.decoction["id"])
    assert D(line["sold"]) == D("300") and D(line["other"]) == D("0")


def test_sales_report(client, shop_a, cat, device):
    h = shop_a.owner_h
    _sell(device, [("Masala tea", 2, [])], payment_mode="cash")  # 40.00
    _sell(device, [("Masala tea", 1, ["Large"]), ("Orange juice", 1, [])], payment_mode="upi")
    wrong = _sell(device, [("Orange juice", 2, [])], payment_mode="cash")  # 120, voided
    _void(client, h, wrong, reason="duplicate").raise_for_status()

    rep = client.get("/api/v1/reports/sales", headers=h).json()
    assert rep["bills"] == 2
    assert rep["total_paise"] == 4000 + 3000 + 6000
    assert rep["by_mode"] == [
        {"mode": "cash", "bills": 1, "total_paise": 4000},
        {"mode": "upi", "bills": 1, "total_paise": 9000},
    ]
    assert rep["items"] == [
        {"name": "Masala tea", "qty": 3, "total_paise": 7000},
        {"name": "Orange juice", "qty": 1, "total_paise": 6000},
    ]
    # Every line at 5%: per-rate taxes add up to the bill totals.
    (five,) = rep["gst_by_rate"]
    assert five["rate_bp"] == 500
    assert five["cgst_paise"] == rep["cgst_paise"] and five["taxable_paise"] == rep["taxable_paise"]
    assert sum(x["total_paise"] for x in rep["by_hour"]) == rep["total_paise"]
    assert [v["invoice_no"] for v in rep["voids"]] == [
        client.get(f"/api/v1/bills/{wrong}", headers=h).json()["invoice_no"]
    ]
    assert rep["voids"][0]["reason"] == "duplicate" and rep["voids"][0]["total_paise"] == 12000
    assert rep["mismatches"] == []

    assert client.get("/api/v1/reports/sales", headers=shop_a.cashier_h).status_code == 403


def test_sales_report_is_per_shop(client, shop_a, shop_b):
    build_catalogue(client, shop_a)
    build_catalogue(client, shop_b)
    FakeDevice(client, shop_b).sync([FakeDevice(client, shop_b).bill([("Masala tea", 5, [])])])
    rep = client.get("/api/v1/reports/sales", headers=shop_a.owner_h).json()
    assert rep["bills"] == 0 and rep["items"] == []


def test_daily_email_figures_leave_voids_out(client, shop_a, cat, device):
    from app.db.session import SessionLocal
    from app.db.tenancy import bind_tenant
    from app.services.reports import daily_figures

    _sell(device, [("Masala tea", 1, [])])
    wrong = _sell(device, [("Masala tea", 1, [])])
    _void(client, shop_a.owner_h, wrong).raise_for_status()
    with SessionLocal() as s:
        bind_tenant(s, shop_a.shop.id)
        f = daily_figures(s, business_date(utcnow()))
    assert (f["bills"], f["total"], f["voids"], f["voided_total"]) == (1, 2000, 1, 2000)
    assert f["top"] == [("Masala tea", 1, 2000)]
