"""SOP history: every recipe change is a new version, and the owner can see them all."""

import pytest

from tests.conftest import build_catalogue


@pytest.fixture
def cat(client, shop_a):
    return build_catalogue(client, shop_a)


def _put_tea(client, h, cat, qty):
    r = client.put(
        f"/api/v1/menu-items/{cat.tea['id']}/recipe",
        json={"lines": [{"ingredient_id": cat.decoction["id"], "qty": qty}]},
        headers=h,
    )
    assert r.status_code == 200, r.text


def test_versions_newest_first_with_who_changed_it(client, shop_a, cat):
    h = shop_a.owner_h
    _put_tea(client, h, cat, "120")
    _put_tea(client, h, cat, "110")
    versions = client.get(f"/api/v1/menu-items/{cat.tea['id']}/recipe/versions", headers=h).json()
    assert [v["version"] for v in versions] == [3, 2, 1]
    assert [v["lines"][0]["qty"] for v in versions] == ["110.000", "120.000", "100.000"]
    owner_name = client.get("/api/v1/auth/me", headers=h).json()["name"]
    assert {v["created_by_name"] for v in versions} == {owner_name}


def test_prep_versions_keep_their_yield(client, shop_a, cat):
    h = shop_a.owner_h
    r = client.put(
        f"/api/v1/ingredients/{cat.decoction['id']}/recipe",
        json={
            "lines": [{"ingredient_id": cat.milk["id"], "qty": "2500"}],
            "yield_qty": "2700",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    versions = client.get(
        f"/api/v1/ingredients/{cat.decoction['id']}/recipe/versions", headers=h
    ).json()
    assert [(v["version"], v["yield_qty"]) for v in versions][0] == (2, "2700.000")
    assert len(versions) == 2


def test_recipe_lines_are_listed_by_ingredient_name(client, shop_a, cat):
    lines = client.get(
        f"/api/v1/ingredients/{cat.decoction['id']}/recipe", headers=shop_a.owner_h
    ).json()["lines"]
    names = [ln["ingredient_name"] for ln in lines]
    assert names == sorted(names, key=str.lower)


def test_cashier_cannot_read_recipe_history(client, shop_a, cat):
    r = client.get(f"/api/v1/menu-items/{cat.tea['id']}/recipe/versions", headers=shop_a.cashier_h)
    assert r.status_code == 403


def test_history_is_tenant_scoped(client, shop_a, shop_b, cat):
    r = client.get(f"/api/v1/menu-items/{cat.tea['id']}/recipe/versions", headers=shop_b.owner_h)
    assert r.status_code == 404
