"""Behaviour of the catalogue, recipes and stock endpoints."""

from decimal import Decimal

from fastapi.testclient import TestClient

from tests.conftest import Catalogue, build_catalogue


def _cat(client, shop) -> Catalogue:
    return build_catalogue(client, shop)


def test_juice_yield_is_converted_to_grams_of_fruit(client: TestClient, shop_a):
    cat = _cat(client, shop_a)
    recipe = client.get(f"/api/v1/menu-items/{cat.juice['id']}/recipe", headers=shop_a.owner_h)
    body = recipe.json()
    # 250 ml / 450 ml per kg * 1000 = 555.556 g, and the inputs are kept for traceability
    assert body["lines"][0]["qty"] == "555.556"
    assert body["yield_inputs"]["ml_per_kg"] == "450"


def test_prep_recipe_cannot_use_another_prep(client, shop_a):
    cat = _cat(client, shop_a)
    h = shop_a.owner_h
    other = client.post(
        "/api/v1/ingredients",
        json={"name": "Lemon syrup", "kind": "prep", "base_unit": "ml"},
        headers=h,
    ).json()
    r = client.put(
        f"/api/v1/ingredients/{other['id']}/recipe",
        json={"yield_qty": "100", "lines": [{"ingredient_id": cat.decoction["id"], "qty": "50"}]},
        headers=h,
    )
    assert r.status_code == 422 and "raw" in r.text


def test_recipe_rejects_duplicates_and_empty(client, shop_a):
    cat = _cat(client, shop_a)
    url = f"/api/v1/menu-items/{cat.tea['id']}/recipe"
    line = {"ingredient_id": cat.sugar["id"], "qty": "5"}
    assert client.put(url, json={"lines": [line, line]}, headers=shop_a.owner_h).status_code == 422
    assert client.put(url, json={"lines": []}, headers=shop_a.owner_h).status_code == 422


def test_stock_in_converts_mixed_units_and_records_what_was_entered(client, shop_a):
    cat = _cat(client, shop_a)
    packet, crate = cat.milk["pack_units"]  # ordered by size
    r = client.post(
        "/api/v1/stock-in",
        json={
            "ingredient_id": cat.milk["id"],
            "packs": [
                {"pack_unit_id": crate["id"], "qty": "3"},
                {"pack_unit_id": packet["id"], "qty": "4"},
            ],
            "loose_qty": "0",
            "cost_paise": 240000,
            "supplier": "Aavin",
        },
        headers=shop_a.owner_h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["base_qty"] == "38000.000"  # 3 x 12000 + 4 x 500
    assert {e["name"] for e in body["entered"]} == {"crate", "packet"}
    milk = client.get(f"/api/v1/ingredients/{cat.milk['id']}", headers=shop_a.owner_h).json()
    assert Decimal(milk["cost_per_unit_paise"]) == Decimal("6.3158")  # 240000 / 38000


def test_unusually_large_stock_in_needs_confirmation(client, shop_a):
    cat = _cat(client, shop_a)
    h = shop_a.owner_h

    def receive(qty, confirm=False):
        return client.post(
            "/api/v1/stock-in",
            json={"ingredient_id": cat.sugar["id"], "loose_qty": qty, "confirm_large": confirm},
            headers=h,
        )

    for _ in range(3):
        assert receive("1000").status_code == 201
    typo = receive("30000")  # "30 bags" instead of "3"
    assert typo.status_code == 409
    assert typo.json()["detail"]["base_qty"] == "30000.000"
    assert receive("30000", confirm=True).status_code == 201


def test_prep_items_cannot_be_received_and_raw_items_cannot_be_batched(client, shop_a):
    cat = _cat(client, shop_a)
    h = shop_a.owner_h
    r = client.post(
        "/api/v1/stock-in",
        json={"ingredient_id": cat.decoction["id"], "loose_qty": "1"},
        headers=h,
    )
    assert r.status_code == 422
    r = client.post(
        "/api/v1/prep-batches",
        json={"ingredient_id": cat.milk["id"], "batches": "1"},
        headers=h,
    )
    assert r.status_code == 422


def test_negative_stock_is_shown_not_blocked(client, shop_a):
    cat = _cat(client, shop_a)
    # A batch made before the morning's milk delivery was entered.
    r = client.post(
        "/api/v1/prep-batches",
        json={"ingredient_id": cat.decoction["id"], "batches": "1"},
        headers=shop_a.cashier_h,
    )
    assert r.status_code == 201
    stock = {s["name"]: s for s in client.get("/api/v1/stock", headers=shop_a.owner_h).json()}
    assert stock["Milk"]["on_hand"] == "-2000.000" and stock["Milk"]["is_negative"]
    assert stock["Tea decoction"]["on_hand"] == "2200.000"


def test_cashier_permissions(client, shop_a):
    cat = _cat(client, shop_a)
    h = shop_a.cashier_h
    assert client.get("/api/v1/stock", headers=h).status_code == 403  # blind counts later
    assert (
        client.post(
            "/api/v1/stock-in", json={"ingredient_id": cat.milk["id"], "loose_qty": "1"}, headers=h
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/menu-items", json={"name": "x", "price_paise": 1}, headers=h
        ).status_code
        == 403
    )
    assert client.get("/api/v1/catalogue", headers=h).status_code == 200


def test_catalogue_etag_saves_bandwidth_until_something_changes(client, shop_a):
    cat = _cat(client, shop_a)
    h = shop_a.cashier_h
    first = client.get("/api/v1/catalogue", headers=h)
    etag = first.headers["etag"]
    body = first.json()
    tea = next(m for m in body["menu_items"] if m["name"] == "Masala tea")
    assert tea["recipe"]["lines"][0]["ingredient_name"] == "Tea decoction"
    assert tea["modifier_ids"] == [cat.less_sugar["id"]]

    assert client.get("/api/v1/catalogue", headers={**h, "If-None-Match": etag}).status_code == 304

    client.patch(
        f"/api/v1/menu-items/{cat.tea['id']}", json={"price_paise": 2500}, headers=shop_a.owner_h
    )
    changed = client.get("/api/v1/catalogue", headers={**h, "If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["etag"] != etag


def test_inactive_items_leave_the_catalogue(client, shop_a):
    cat = _cat(client, shop_a)
    client.patch(
        f"/api/v1/menu-items/{cat.juice['id']}", json={"is_active": False}, headers=shop_a.owner_h
    )
    names = [
        m["name"]
        for m in client.get("/api/v1/catalogue", headers=shop_a.owner_h).json()["menu_items"]
    ]
    assert names == ["Masala tea"]


def test_duplicate_names_conflict(client, shop_a):
    _cat(client, shop_a)
    r = client.post(
        "/api/v1/ingredients", json={"name": "Milk", "base_unit": "ml"}, headers=shop_a.owner_h
    )
    assert r.status_code == 409
