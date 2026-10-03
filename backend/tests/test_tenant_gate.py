"""PHASE 0 GATE (extended every phase): a user from shop A can never read or
write shop B's data, by URL id or by ids smuggled inside a request body.

test_every_id_route_is_covered fails whenever an endpoint with an {id} in its
path is added (or gains a method) without being listed here, so this gate keeps
protecting every future phase automatically.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import Catalogue, FakeDevice, ShopFixture, build_catalogue

ANY_ID = str(uuid.uuid4())  # bodies must be schema-valid so a 404 can only come from the lookup

# template -> (how to find shop B's id for it, {method: body})
ID_ROUTES = {
    "/api/v1/users/{user_id}": ("cashier", {"GET": None, "PATCH": {"name": "hijacked"}}),
    "/api/v1/devices/{device_id}": ("device", {"GET": None, "PATCH": {"name": "hijacked"}}),
    "/api/v1/ingredients/{ingredient_id}": (
        "cat.milk",
        {"GET": None, "PATCH": {"name": "hijacked"}},
    ),
    "/api/v1/modifiers/{modifier_id}/menu-items": (
        "cat.less_sugar",
        {"PUT": {"menu_item_ids": []}},
    ),
    "/api/v1/ingredients/{ingredient_id}/pack-units": (
        "cat.milk",
        {"GET": None, "POST": {"name": "hijack", "qty_in_base": "1"}},
    ),
    "/api/v1/ingredients/{ingredient_id}/recipe": (
        "cat.decoction",
        {"GET": None, "PUT": {"yield_qty": "1", "lines": [{"ingredient_id": ANY_ID, "qty": "1"}]}},
    ),
    "/api/v1/ingredients/{ingredient_id}/recipe/versions": ("cat.decoction", {"GET": None}),
    "/api/v1/menu-items/{menu_item_id}": (
        "cat.tea",
        {"GET": None, "PATCH": {"name": "hijacked"}},
    ),
    "/api/v1/menu-items/{menu_item_id}/recipe": (
        "cat.tea",
        {"GET": None, "PUT": {"lines": [{"ingredient_id": ANY_ID, "qty": "1"}]}},
    ),
    "/api/v1/menu-items/{menu_item_id}/recipe/versions": ("cat.tea", {"GET": None}),
    "/api/v1/menu-items/{menu_item_id}/modifiers": ("cat.tea", {"PUT": {"modifier_ids": []}}),
    "/api/v1/modifiers/{modifier_id}": (
        "cat.less_sugar",
        {"GET": None, "PATCH": {"name": "hijacked"}},
    ),
    "/api/v1/stock/{ingredient_id}/ledger": ("cat.milk", {"GET": None}),
    "/api/v1/bills/{bill_id}": ("bill", {"GET": None}),
    "/api/v1/bills/{bill_id}/void": ("bill", {"POST": {"reason": "wrong_item"}}),
    "/api/v1/devices/{device_id}/sync-state": ("device", {"GET": None}),
}


# Routes keyed by a business DATE, not an id: there is no foreign id to smuggle.
# Their risk is different (shop A reading shop B's count for the same date), so
# each one must appear here AND be exercised by test_day_counts_are_per_shop.
DATE_ROUTES = {
    ("/api/v1/day-counts/{business_date}/sheet", "GET"),
    ("/api/v1/day-counts/{business_date}/counts", "POST"),
    ("/api/v1/day-counts/{business_date}/report", "GET"),
    ("/api/v1/day-counts/{business_date}/approve", "POST"),
}


def _foreign_id(shop: ShopFixture, cat: Catalogue, key: str) -> str:
    if key == "bill":
        return cat.bill_id
    if key.startswith("cat."):
        return getattr(cat, key[4:])["id"]
    return str(getattr(shop, key).id)


def _url(template: str, obj_id: str) -> str:
    start, end = template.index("{"), template.index("}")
    return template[:start] + obj_id + template[end + 1 :]


def _with_bill(client, shop) -> Catalogue:
    cat = build_catalogue(client, shop)
    device = FakeDevice(client, shop)
    bill = device.bill([("Masala tea", 1, [])])
    assert device.sync([bill]).json()["results"][0]["status"] == "accepted"
    cat.bill_id = bill["id"]
    return cat


@pytest.fixture
def two_shops(client, shop_a, shop_b):
    return shop_a, shop_b, _with_bill(client, shop_a), _with_bill(client, shop_b)


def test_every_id_route_is_covered():
    actual = {
        (path, method.upper())
        for path, ops in app.openapi()["paths"].items()
        if "{" in path and path.startswith("/api/")
        for method in ops
    }
    covered = {(t, m) for t, (_, calls) in ID_ROUTES.items() for m in calls}
    missing = actual - covered - DATE_ROUTES
    assert not missing, f"Add these to ID_ROUTES in the tenant gate: {sorted(missing)}"


def test_other_shops_ids_are_404_for_every_method(client: TestClient, two_shops):
    shop_a, shop_b, _, cat_b = two_shops
    for template, (key, calls) in ID_ROUTES.items():
        url = _url(template, _foreign_id(shop_b, cat_b, key))
        for method, body in calls.items():
            r = client.request(method, url, json=body, headers=shop_a.owner_h)
            assert r.status_code == 404, f"{method} {template} leaked: {r.status_code} {r.text}"


def test_shop_b_data_is_unchanged_after_the_attack(client: TestClient, two_shops):
    shop_a, shop_b, _, cat_b = two_shops

    def snapshot():
        return {
            t: client.get(_url(t, _foreign_id(shop_b, cat_b, key)), headers=shop_b.owner_h).json()
            for t, (key, calls) in ID_ROUTES.items()
            if "GET" in calls
        }

    before = snapshot()
    for template, (key, calls) in ID_ROUTES.items():
        url = _url(template, _foreign_id(shop_b, cat_b, key))
        for method, body in calls.items():
            if method != "GET":
                client.request(method, url, json=body, headers=shop_a.owner_h)
    assert snapshot() == before


def test_lists_only_show_own_shop(client: TestClient, two_shops):
    shop_a, _, cat_a, _ = two_shops
    h = shop_a.owner_h
    users = client.get("/api/v1/users", headers=h).json()
    assert {u["id"] for u in users} == {str(shop_a.owner.id), str(shop_a.cashier.id)}
    assert [d["id"] for d in client.get("/api/v1/devices", headers=h).json()] == [
        str(shop_a.device.id)
    ]
    ingredient_ids = {i["id"] for i in client.get("/api/v1/ingredients", headers=h).json()}
    assert cat_a.milk["id"] in ingredient_ids and len(ingredient_ids) == 5
    assert len(client.get("/api/v1/menu-items", headers=h).json()) == 2
    assert len(client.get("/api/v1/modifiers", headers=h).json()) == 1
    assert len(client.get("/api/v1/stock", headers=h).json()) == 5
    catalogue = client.get("/api/v1/catalogue", headers=h).json()
    assert {m["id"] for m in catalogue["menu_items"]} == {cat_a.tea["id"], cat_a.juice["id"]}


def test_other_shops_ids_inside_request_bodies_are_rejected(client: TestClient, two_shops):
    shop_a, _, cat_a, cat_b = two_shops
    h = shop_a.owner_h
    # recipe on MY item using THEIR ingredient
    r = client.put(
        f"/api/v1/menu-items/{cat_a.tea['id']}/recipe",
        json={"lines": [{"ingredient_id": cat_b.milk["id"], "qty": "10"}]},
        headers=h,
    )
    assert r.status_code == 422
    # my item linked to THEIR modifier
    r = client.put(
        f"/api/v1/menu-items/{cat_a.tea['id']}/modifiers",
        json={"modifier_ids": [cat_b.less_sugar["id"]]},
        headers=h,
    )
    assert r.status_code == 422
    # my modifier offered on THEIR drink
    my_mod = client.get("/api/v1/modifiers", headers=h).json()[0]
    r = client.put(
        f"/api/v1/modifiers/{my_mod['id']}/menu-items",
        json={"menu_item_ids": [cat_b.tea["id"]]},
        headers=h,
    )
    assert r.status_code == 422
    # modifier using THEIR ingredient
    r = client.post(
        "/api/v1/modifiers",
        json={"name": "x", "lines": [{"ingredient_id": cat_b.sugar["id"], "qty_delta": "1"}]},
        headers=h,
    )
    assert r.status_code == 422
    # stock-in to MY milk using THEIR pack unit
    r = client.post(
        "/api/v1/stock-in",
        json={
            "ingredient_id": cat_a.milk["id"],
            "packs": [{"pack_unit_id": cat_b.milk["pack_units"][0]["id"], "qty": "1"}],
        },
        headers=h,
    )
    assert r.status_code == 422
    # stock-in / prep batch on THEIR ingredient
    assert (
        client.post(
            "/api/v1/stock-in",
            json={"ingredient_id": cat_b.milk["id"], "loose_qty": "5"},
            headers=h,
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/prep-batches",
            json={"ingredient_id": cat_b.decoction["id"], "batches": "1"},
            headers=h,
        ).status_code
        == 404
    )


def test_shop_endpoint_is_always_the_callers_shop(client: TestClient, shop_a, shop_b):
    r = client.patch("/api/v1/shop", json={"name": "Renamed A"}, headers=shop_a.owner_h)
    assert r.status_code == 200 and r.json()["id"] == str(shop_a.shop.id)
    assert client.get("/api/v1/shop", headers=shop_b.owner_h).json()["name"] == "Shop B"


def test_new_rows_land_in_callers_shop_even_if_client_sends_shop_id(
    client: TestClient, shop_a, shop_b
):
    r = client.post(
        "/api/v1/devices",
        json={"name": "Sneaky", "shop_id": str(shop_b.shop.id)},
        headers=shop_a.owner_h,
    )
    assert r.status_code == 201
    b_devices = client.get("/api/v1/devices", headers=shop_b.owner_h).json()
    assert all(d["name"] != "Sneaky" for d in b_devices)


def test_day_counts_are_per_shop(client: TestClient, two_shops):
    """Same date, two shops: B's count, report and approval never touch A's day."""
    from app.core.time import business_date, utcnow

    shop_a, shop_b, cat_a, cat_b = two_shops
    day = business_date(utcnow()).isoformat()
    base = f"/api/v1/day-counts/{day}"
    r = client.post(
        f"{base}/counts",
        json={"lines": [{"ingredient_id": cat_b.milk["id"], "loose_qty": "0"}]},
        headers=shop_b.owner_h,
    )
    assert r.status_code == 200, r.text
    # Shop A cannot count shop B's ingredient...
    r = client.post(
        f"{base}/counts",
        json={"lines": [{"ingredient_id": cat_b.milk["id"], "loose_qty": "1"}]},
        headers=shop_a.owner_h,
    )
    assert r.status_code == 422
    # ...and sees none of B's day: nothing counted, no report lines.
    sheet = client.get(f"{base}/sheet", headers=shop_a.owner_h).json()
    assert not any(i["counted"] for i in sheet["items"])
    assert cat_b.milk["id"] not in {i["ingredient_id"] for i in sheet["items"]}
    assert client.get(f"{base}/report", headers=shop_a.owner_h).json()["lines"] == []
    # Approving A's (empty) day is refused and leaves B's day alone.
    assert client.post(f"{base}/approve", headers=shop_a.owner_h).status_code == 422
    b = client.get(f"{base}/report", headers=shop_b.owner_h).json()
    assert [ln["ingredient_id"] for ln in b["lines"]] == [cat_b.milk["id"]]
