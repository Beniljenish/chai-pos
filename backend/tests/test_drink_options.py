"""Options on the bill (Large, Less sugar...): the owner creates them and picks
which drinks offer them, from the option's side as well as the drink's."""

import pytest

from tests.conftest import FakeDevice, build_catalogue


@pytest.fixture
def cat(client, shop_a):
    return build_catalogue(client, shop_a)


def _mods(client, h):
    return {m["name"]: m for m in client.get("/api/v1/modifiers", headers=h).json()}


def test_owner_view_lists_the_drinks_offering_each_option(client, shop_a, cat):
    less = _mods(client, shop_a.owner_h)["Less sugar"]
    assert less["menu_item_ids"] == [cat.tea["id"]]
    one = client.get(f"/api/v1/modifiers/{less['id']}", headers=shop_a.owner_h).json()
    assert one["menu_item_ids"] == [cat.tea["id"]]


def test_offer_an_option_on_several_drinks_at_once(client, shop_a, cat):
    h = shop_a.owner_h
    less = cat.less_sugar
    r = client.put(
        f"/api/v1/modifiers/{less['id']}/menu-items",
        json={"menu_item_ids": [cat.tea["id"], cat.juice["id"]]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["menu_item_ids"]) == {cat.tea["id"], cat.juice["id"]}
    menu = {m["name"]: m for m in client.get("/api/v1/catalogue", headers=h).json()["menu_items"]}
    assert menu["Orange juice"]["modifier_ids"] == [less["id"]]

    # Replacing the set touches only this option, never the drink's other options.
    large = client.post(
        "/api/v1/modifiers", json={"name": "Large", "scale_factor": "1.5"}, headers=h
    ).json()
    client.put(
        f"/api/v1/modifiers/{large['id']}/menu-items",
        json={"menu_item_ids": [cat.tea["id"]]},
        headers=h,
    ).raise_for_status()
    client.put(
        f"/api/v1/modifiers/{less['id']}/menu-items", json={"menu_item_ids": []}, headers=h
    ).raise_for_status()
    menu = {m["name"]: m for m in client.get("/api/v1/catalogue", headers=h).json()["menu_items"]}
    assert menu["Masala tea"]["modifier_ids"] == [large["id"]]
    assert menu["Orange juice"]["modifier_ids"] == []


def test_links_to_a_drink_off_the_menu_survive(client, shop_a, cat):
    """The owner screen sends the drinks it shows; a drink taken off the menu
    keeps its options for when it comes back."""
    h = shop_a.owner_h
    client.patch(f"/api/v1/menu-items/{cat.tea['id']}", json={"is_active": False}, headers=h)
    less = _mods(client, h)["Less sugar"]
    assert less["menu_item_ids"] == [cat.tea["id"]]  # still visible to the owner


def test_cashier_cannot_assign_and_unknown_drinks_are_refused(client, shop_a, cat):
    url = f"/api/v1/modifiers/{cat.less_sugar['id']}/menu-items"
    assert client.put(url, json={"menu_item_ids": []}, headers=shop_a.cashier_h).status_code == 403
    r = client.put(
        url,
        json={"menu_item_ids": ["00000000-0000-0000-0000-000000000000"]},
        headers=shop_a.owner_h,
    )
    assert r.status_code == 422


def test_duplicate_option_name_is_a_clear_409(client, shop_a, cat):
    r = client.post("/api/v1/modifiers", json={"name": "Less sugar"}, headers=shop_a.owner_h)
    assert r.status_code == 409
    assert "option" in r.json()["detail"].lower()


def test_new_drink_with_large_bills_and_deducts_end_to_end(client, shop_a, cat):
    """The whole owner flow: new drink, its recipe, a Large option, then a sale."""
    h = shop_a.owner_h
    ginger = client.post(
        "/api/v1/menu-items", json={"name": "Ginger tea", "price_paise": 2500}, headers=h
    ).json()
    client.put(
        f"/api/v1/menu-items/{ginger['id']}/recipe",
        json={
            "lines": [
                {"ingredient_id": cat.decoction["id"], "qty": "100"},
                {"ingredient_id": cat.sugar["id"], "qty": "8"},
            ]
        },
        headers=h,
    ).raise_for_status()
    large = client.post(
        "/api/v1/modifiers",
        json={
            "name": "Large",
            "price_delta_paise": 1000,
            "scale_factor": "1.5",
            "lines": [{"ingredient_id": cat.sugar["id"], "qty_delta": "2"}],
        },
        headers=h,
    ).json()
    client.put(
        f"/api/v1/modifiers/{large['id']}/menu-items",
        json={"menu_item_ids": [ginger["id"]]},
        headers=h,
    ).raise_for_status()

    device = FakeDevice(client, shop_a)
    r = device.sync([device.bill([("Ginger tea", 2, ["Large"])])])
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["status"] in ("accepted", "created"), r.text

    def sold(ingredient_id):
        rows = client.get(f"/api/v1/stock/{ingredient_id}/ledger", headers=h).json()
        return [x["qty_delta"] for x in rows if x["reason"] == "sale"]

    # per cup: decoction 100 x 1.5 = 150; sugar 8 x 1.5 + 2 = 14. Two cups.
    assert sold(cat.decoction["id"]) == ["-300.000"]
    assert sold(cat.sugar["id"]) == ["-28.000"]
