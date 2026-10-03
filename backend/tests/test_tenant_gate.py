"""PHASE 0 GATE: a user from shop A can never read or write shop B's data.

The coverage test at the bottom fails whenever someone adds an endpoint with
an {id} in its path without adding it to ID_ROUTES here, so the gate keeps
protecting future phases automatically.
"""

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import ShopFixture

# path template -> (fixture attribute that holds shop B's object, PATCH body)
ID_ROUTES = {
    "/api/v1/users/{user_id}": ("cashier", {"name": "hijacked"}),
    "/api/v1/devices/{device_id}": ("device", {"name": "hijacked"}),
}


def _path(template: str, obj_id) -> str:
    return template.split("{")[0] + str(obj_id)


def test_every_id_route_is_covered_by_this_gate():
    templated = {p for p in app.openapi()["paths"] if "{" in p and p.startswith("/api/")}
    missing = templated - ID_ROUTES.keys()
    assert not missing, f"Add these routes to ID_ROUTES in the tenant gate: {missing}"


def test_cannot_read_other_shops_rows_by_id(client: TestClient, shop_a, shop_b):
    for template, (attr, _) in ID_ROUTES.items():
        foreign_id = getattr(shop_b, attr).id
        r = client.get(_path(template, foreign_id), headers=shop_a.owner_h)
        assert r.status_code == 404, f"GET {template} leaked: {r.status_code} {r.text}"


def test_cannot_modify_other_shops_rows_by_id(client: TestClient, shop_a, shop_b):
    for template, (attr, body) in ID_ROUTES.items():
        foreign = getattr(shop_b, attr)
        r = client.patch(_path(template, foreign.id), json=body, headers=shop_a.owner_h)
        assert r.status_code == 404, f"PATCH {template} leaked: {r.status_code}"
        # and shop B's row really is unchanged
        own = client.get(_path(template, foreign.id), headers=shop_b.owner_h)
        assert own.json()["name"] != "hijacked"


def test_lists_only_show_own_shop(client: TestClient, shop_a: ShopFixture, shop_b):
    users = client.get("/api/v1/users", headers=shop_a.owner_h).json()
    assert {u["id"] for u in users} == {str(shop_a.owner.id), str(shop_a.cashier.id)}
    devices = client.get("/api/v1/devices", headers=shop_a.owner_h).json()
    assert [d["id"] for d in devices] == [str(shop_a.device.id)]


def test_shop_endpoint_is_always_the_callers_shop(client: TestClient, shop_a, shop_b):
    r = client.patch("/api/v1/shop", json={"name": "Renamed A"}, headers=shop_a.owner_h)
    assert r.status_code == 200 and r.json()["id"] == str(shop_a.shop.id)
    b = client.get("/api/v1/shop", headers=shop_b.owner_h).json()
    assert b["name"] == "Shop B"


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
    a_devices = client.get("/api/v1/devices", headers=shop_a.owner_h).json()
    assert any(d["name"] == "Sneaky" for d in a_devices)
