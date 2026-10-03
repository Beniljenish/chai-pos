"""Opening stock: the first physical count, once per ingredient."""

from decimal import Decimal as D

import pytest

from tests.conftest import FakeDevice, build_catalogue


@pytest.fixture
def cat(client, shop_a):
    return build_catalogue(client, shop_a)


def _stock(client, h, ingredient_id):
    rows = client.get("/api/v1/stock", headers=h).json()
    return next(r for r in rows if r["ingredient_id"] == ingredient_id)


def _packs(client, h, ingredient_id):
    units = client.get(f"/api/v1/ingredients/{ingredient_id}", headers=h).json()["pack_units"]
    return {u["name"]: u["id"] for u in units}


def test_opening_counts_by_pack_and_sets_on_hand(client, shop_a, cat):
    h = shop_a.owner_h
    packs = _packs(client, h, cat.milk["id"])
    assert _stock(client, h, cat.milk["id"])["has_opening"] is False
    res = client.post(
        "/api/v1/stock/opening",
        json={
            "ingredient_id": cat.milk["id"],
            "packs": [{"pack_unit_id": packs["packet"], "qty": "3"}],
            "loose_qty": "200",
        },
        headers=h,
    )
    assert res.status_code == 201, res.text
    assert D(res.json()["counted_qty"]) == D("1700")
    row = _stock(client, h, cat.milk["id"])
    assert D(row["on_hand"]) == D("1700") and row["has_opening"] is True


def test_opening_absorbs_sales_made_before_it(client, shop_a, cat):
    """Billing started before anyone counted: on hand is negative. The opening
    count is the truth, so the adjustment is counted minus what the system said."""
    h = shop_a.owner_h
    device = FakeDevice(client, shop_a)
    r = device.sync([device.bill([("Masala tea", 3, [])])])  # 300 ml decoction
    assert r.json()["results"][0]["status"] == "accepted"
    assert D(_stock(client, h, cat.decoction["id"])["on_hand"]) == D("-300")

    res = client.post(
        "/api/v1/stock/opening",
        json={"ingredient_id": cat.decoction["id"], "loose_qty": "1000"},
        headers=h,
    )
    assert D(res.json()["system_qty"]) == D("-300")
    assert D(_stock(client, h, cat.decoction["id"])["on_hand"]) == D("1000")
    ledger = client.get(f"/api/v1/stock/{cat.decoction['id']}/ledger", headers=h).json()
    assert [(r["reason"], r["qty_delta"]) for r in ledger if r["reason"] == "opening"] == [
        ("opening", "1300.000")
    ]


def test_opening_of_zero_is_recorded_without_a_ledger_row(client, shop_a, cat):
    h = shop_a.owner_h
    res = client.post("/api/v1/stock/opening", json={"ingredient_id": cat.sugar["id"]}, headers=h)
    assert res.status_code == 201, res.text
    assert _stock(client, h, cat.sugar["id"])["has_opening"] is True
    assert client.get(f"/api/v1/stock/{cat.sugar['id']}/ledger", headers=h).json() == []


def test_opening_can_only_be_entered_once(client, shop_a, cat):
    h = shop_a.owner_h
    body = {"ingredient_id": cat.oranges["id"], "loose_qty": "5000"}
    assert client.post("/api/v1/stock/opening", json=body, headers=h).status_code == 201
    again = client.post("/api/v1/stock/opening", json={**body, "loose_qty": "9000"}, headers=h)
    assert again.status_code == 409
    assert "day-end count" in again.json()["detail"]
    assert D(_stock(client, h, cat.oranges["id"])["on_hand"]) == D("5000")


def test_cashier_cannot_enter_opening_stock(client, shop_a, cat):
    res = client.post(
        "/api/v1/stock/opening",
        json={"ingredient_id": cat.milk["id"], "loose_qty": "1"},
        headers=shop_a.cashier_h,
    )
    assert res.status_code == 403


def test_pack_from_another_ingredient_is_refused(client, shop_a, cat):
    h = shop_a.owner_h
    sugar_bag = _packs(client, h, cat.sugar["id"])["bag"]
    res = client.post(
        "/api/v1/stock/opening",
        json={
            "ingredient_id": cat.milk["id"],
            "packs": [{"pack_unit_id": sugar_bag, "qty": "1"}],
        },
        headers=h,
    )
    assert res.status_code == 422
    assert _stock(client, h, cat.milk["id"])["has_opening"] is False


def test_openings_are_tenant_scoped(client, shop_a, shop_b, cat):
    client.post(
        "/api/v1/stock/opening",
        json={"ingredient_id": cat.milk["id"], "loose_qty": "500"},
        headers=shop_a.owner_h,
    )
    # Shop B cannot open stock on shop A's ingredient: it does not exist for B.
    res = client.post(
        "/api/v1/stock/opening",
        json={"ingredient_id": cat.milk["id"], "loose_qty": "1"},
        headers=shop_b.owner_h,
    )
    assert res.status_code == 404
