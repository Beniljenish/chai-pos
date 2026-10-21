# ruff: noqa: F811  (fixtures imported from other test modules are used as arguments)
"""Dish options for food court customers: Large, less sugar and so on, priced and saved by the
server from the outlet's own options (services/online.py), plus the description, photo and veg
mark an owner sets."""

import uuid

import pytest

from app.services import onlinepay
from app.services.gst import LineIn, compute_bill
from tests.test_food_court import API, _live, _menu, court  # noqa: F401
from tests.test_online_payments import _pay, _start, _status, rzp  # noqa: F401


def _make_options(client, shop):
    """Large (+₹10, 1.5x the drink) and Jumbo (2x) as sizes, Less sugar from the catalogue."""
    h = shop.owner_h
    items = {m["name"]: m for m in client.get(f"{API}/menu-items", headers=h).json()}
    mods = {m["name"]: m for m in client.get(f"{API}/modifiers", headers=h).json()}
    ingredient = client.get(f"{API}/ingredients", headers=h).json()[0]["id"]
    out = {}
    for name, delta, scale in (("Large", 1000, "1.5"), ("Jumbo", 2000, "2")):
        r = client.post(
            f"{API}/modifiers",
            json={
                "name": name,
                "price_delta_paise": delta,
                "scale_factor": scale,
                "lines": [{"ingredient_id": ingredient, "qty_delta": "10"}],
            },
            headers=h,
        )
        assert r.status_code == 201, r.text
        out[name] = r.json()
    out["Less sugar"] = mods["Less sugar"]
    tea = items["Masala tea"]["id"]
    client.put(
        f"{API}/menu-items/{tea}/modifiers",
        json={"modifier_ids": [out["Less sugar"]["id"], out["Large"]["id"], out["Jumbo"]["id"]]},
        headers=h,
    ).raise_for_status()
    return out


def _place(client, c, picks, which="a", who=None):
    """picks: [(dish name, qty, [option ids])]"""
    menu = _menu(client, c, which)
    body = {
        "request_id": str(uuid.uuid4()),
        "items": [
            {"menu_item_id": menu[n]["id"], "qty": q, "modifier_ids": mods} for n, q, mods in picks
        ],
    }
    return client.post(
        f"{API}/public/courts/{c['slug']}/outlets/{c[which]}/orders",
        json=body,
        headers=who or c["customer"],
    )


def _gst_total(shop_gst_type, lines):
    return compute_bill(
        [LineIn(price, qty, 500, True, (delta,)) for price, qty, delta in lines], shop_gst_type
    ).total


def test_the_public_menu_lists_the_options_each_dish_offers(client, shop_a, court):
    opts = _make_options(client, shop_a)
    tea = _menu(client, court)["Masala tea"]
    got = {o["name"]: o for o in tea["options"]}
    assert set(got) == {"Less sugar", "Large", "Jumbo"}
    assert got["Large"]["is_size"] is True and got["Large"]["price_delta_paise"] == 1000
    assert got["Less sugar"]["is_size"] is False and got["Less sugar"]["price_delta_paise"] == 0
    assert got["Large"]["id"] == opts["Large"]["id"]
    assert _menu(client, court)["Orange juice"]["options"] == []
    # a switched-off option is not offered
    client.patch(
        f"{API}/modifiers/{opts['Jumbo']['id']}", json={"is_active": False}, headers=shop_a.owner_h
    ).raise_for_status()
    assert {o["name"] for o in _menu(client, court)["Masala tea"]["options"]} == {
        "Less sugar",
        "Large",
    }


def test_an_option_changes_the_price_and_is_saved_on_the_order_like_the_tills(
    client, shop_a, court
):
    opts = _make_options(client, shop_a)
    r = _place(client, court, [("Masala tea", 2, [opts["Large"]["id"], opts["Less sugar"]["id"]])])
    assert r.status_code == 201, r.text
    line = next(o for o in _live(client, shop_a) if o["id"] == r.json()["order_id"])["state"][
        "lines"
    ][0]
    assert line["unit_price_paise"] == 2000  # the dish's own price...
    assert {m["name"] for m in line["modifiers"]} == {"Large", "Less sugar"}  # ...and its options
    large = next(m for m in line["modifiers"] if m["name"] == "Large")
    assert large["price_delta_paise"] == 1000 and large["scale_factor"] == "1.500"
    assert large["lines"] and large["lines"][0]["qty_delta"] == "10.000"
    assert set(large) == {"modifier_id", "name", "price_delta_paise", "scale_factor", "lines"}
    # the customer's status page and My orders name the options
    status = client.get(f"{API}/public/orders/{r.json()['status_key']}").json()
    assert status["items"] == [{"name": "Masala tea (Large, Less sugar)", "qty": 2}]
    from app.models import GstType

    assert status["total_paise"] == _gst_total(GstType.regular, [(2000, 2, 1000)])


def test_the_same_dish_with_different_options_is_separate_lines(client, shop_a, court):
    opts = _make_options(client, shop_a)
    r = _place(
        client,
        court,
        [("Masala tea", 1, []), ("Masala tea", 2, [opts["Large"]["id"]]), ("Masala tea", 1, [])],
    )
    assert r.status_code == 201, r.text
    lines = next(o for o in _live(client, shop_a) if o["id"] == r.json()["order_id"])["state"][
        "lines"
    ]
    assert sorted((len(ln["modifiers"]), ln["qty"]) for ln in lines) == [(0, 2), (1, 2)]


@pytest.mark.parametrize("bad", ["other_dish", "unknown", "two_sizes", "switched_off"])
def test_options_the_dish_does_not_offer_are_refused_and_nothing_is_placed(
    client, shop_a, court, bad
):
    opts = _make_options(client, shop_a)
    juice_only = client.post(
        f"{API}/modifiers", json={"name": "Chilled", "lines": []}, headers=shop_a.owner_h
    ).json()
    pick = {
        "other_dish": [("Masala tea", 1, [juice_only["id"]])],  # exists, not offered on tea
        "unknown": [("Masala tea", 1, [str(uuid.uuid4())])],
        "two_sizes": [("Masala tea", 1, [opts["Large"]["id"], opts["Jumbo"]["id"]])],
        "switched_off": [("Masala tea", 1, [opts["Large"]["id"]])],
    }[bad]
    if bad == "switched_off":
        client.patch(
            f"{API}/modifiers/{opts['Large']['id']}",
            json={"is_active": False},
            headers=shop_a.owner_h,
        ).raise_for_status()
    r = _place(client, court, pick)
    assert r.status_code in (409, 422), r.text
    assert _live(client, shop_a) == []


def test_a_phone_cannot_name_a_price_for_an_option(client, shop_a, court):
    opts = _make_options(client, shop_a)
    menu = _menu(client, court)
    r = client.post(
        f"{API}/public/courts/{court['slug']}/outlets/{court['a']}/orders",
        json={
            "request_id": str(uuid.uuid4()),
            "items": [
                {
                    "menu_item_id": menu["Masala tea"]["id"],
                    "qty": 1,
                    "modifier_ids": [opts["Large"]["id"]],
                    "price_delta_paise": 0,  # ignored: the server uses its own
                }
            ],
        },
        headers=court["customer"],
    )
    assert r.status_code == 201
    line = next(o for o in _live(client, shop_a) if o["id"] == r.json()["order_id"])["state"][
        "lines"
    ][0]
    assert line["modifiers"][0]["price_delta_paise"] == 1000


def test_paying_online_for_a_dish_with_options_charges_the_options_too(client, shop_a, court, rzp):
    opts = _make_options(client, shop_a)
    menu = _menu(client, court)
    body = {
        "checkout_id": str(uuid.uuid4()),
        "slug": court["slug"],
        "message_ok": False,
        "orders": [
            {
                "outlet_id": court["a"],
                "request_id": str(uuid.uuid4()),
                "items": [
                    {
                        "menu_item_id": menu["Masala tea"]["id"],
                        "qty": 2,
                        "modifier_ids": [opts["Large"]["id"]],
                    }
                ],
            }
        ],
    }
    started = client.post(f"{API}/customer/checkout", json=body, headers=court["customer"]).json()
    from app.models import GstType

    assert started["amount_paise"] == _gst_total(GstType.regular, [(2000, 2, 1000)])
    _pay(client, rzp, started)
    done = _status(client, court, started["id"]).json()
    assert done["fulfilled"] and done["orders"][0]["token"]
    line = _live(client, shop_a)[0]["state"]["lines"][0]
    assert [m["name"] for m in line["modifiers"]] == ["Large"]
    assert rzp.refunds == []


def test_an_option_that_went_off_while_paying_is_refunded(client, shop_a, court, rzp):
    opts = _make_options(client, shop_a)
    menu = _menu(client, court)
    body = {
        "checkout_id": str(uuid.uuid4()),
        "slug": court["slug"],
        "orders": [
            {
                "outlet_id": court["a"],
                "request_id": str(uuid.uuid4()),
                "items": [
                    {
                        "menu_item_id": menu["Masala tea"]["id"],
                        "qty": 1,
                        "modifier_ids": [opts["Large"]["id"]],
                    }
                ],
            }
        ],
    }
    started = client.post(f"{API}/customer/checkout", json=body, headers=court["customer"]).json()
    client.patch(
        f"{API}/modifiers/{opts['Large']['id']}", json={"is_active": False}, headers=shop_a.owner_h
    ).raise_for_status()
    _pay(client, rzp, started)
    done = _status(client, court, started["id"]).json()
    assert done["orders"][0]["error"] == "items_unavailable" and done["orders"][0]["refunded"]
    assert _live(client, shop_a) == []


def test_a_payment_saved_before_options_existed_still_places(client):
    assert onlinepay._with_mods(["abc", 2]) == ["abc", 2, []]
    assert onlinepay._with_mods(["abc", 2, ["m"]]) == ["abc", 2, ["m"]]


# ---------------------------------------------------------------- what the owner sets per dish
def test_the_owner_sets_description_photo_and_veg_and_customers_see_them(client, shop_a, court):
    tea = _menu(client, court)["Masala tea"]
    r = client.patch(
        f"{API}/menu-items/{tea['id']}",
        json={
            "description": "Strong tea with ginger",
            "photo_url": "https://example.com/tea.jpg",
            "is_veg": False,
        },
        headers=shop_a.owner_h,
    )
    assert r.status_code == 200 and r.json()["description"] == "Strong tea with ginger"
    seen = _menu(client, court)["Masala tea"]
    assert seen["description"] == "Strong tea with ginger"
    assert seen["photo_url"] == "https://example.com/tea.jpg" and seen["is_veg"] is False
    # defaults for a dish nobody described: vegetarian, no photo
    juice = _menu(client, court)["Orange juice"]
    assert juice["description"] == "" and juice["photo_url"] == "" and juice["is_veg"] is True


@pytest.mark.parametrize("link", ["http://example.com/a.jpg", "javascript:alert(1)", "//x.com/a"])
def test_a_photo_link_must_be_https(client, shop_a, court, link):
    tea = _menu(client, court)["Masala tea"]
    r = client.patch(
        f"{API}/menu-items/{tea['id']}", json={"photo_url": link}, headers=shop_a.owner_h
    )
    assert r.status_code == 422


def test_only_the_owner_edits_what_customers_see(client, shop_a, court):
    tea = _menu(client, court)["Masala tea"]
    r = client.patch(
        f"{API}/menu-items/{tea['id']}", json={"description": "x"}, headers=shop_a.cashier_h
    )
    assert r.status_code == 403


# ---- the pictures that ship with the app
def test_a_shipped_picture_is_a_valid_photo_and_other_paths_are_not(client, shop_a, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    ok = client.patch(
        f"{API}/menu-items/{tea}", json={"photo_url": "/dishes/tea.svg"}, headers=shop_a.owner_h
    )
    assert ok.status_code == 200 and ok.json()["photo_url"] == "/dishes/tea.svg"
    assert _menu(client, court)["Masala tea"]["photo_url"] == "/dishes/tea.svg"
    for bad in (
        "/dishes/../secret.svg",
        "/etc/passwd",
        "/dishes/tea.png",
        "/dishes/Tea.svg",
        "data:image/svg+xml,x",
    ):
        r = client.patch(f"{API}/menu-items/{tea}", json={"photo_url": bad}, headers=shop_a.owner_h)
        assert r.status_code == 422, bad
    # taking the picture off is allowed
    gone = client.patch(f"{API}/menu-items/{tea}", json={"photo_url": ""}, headers=shop_a.owner_h)
    assert gone.status_code == 200 and gone.json()["photo_url"] == ""


def test_the_sample_menu_comes_with_pictures_and_descriptions(client):
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.db.tenancy import mark_system
    from app.models import MenuItem
    from app.services.sample import seed_catalogue
    from app.services.shops import create_shop

    shop, owner = create_shop("Sample Outlet", "9841100003")
    seed_catalogue(shop, owner)
    with mark_system(SessionLocal()) as db:
        items = {m.name: m for m in db.scalars(select(MenuItem).where(MenuItem.shop_id == shop.id))}
    assert items["Masala tea"].photo_url == "/dishes/tea.svg"
    assert items["Orange juice"].photo_url == "/dishes/juice.svg"
    assert items["Masala tea"].description and items["Orange juice"].is_veg is True


def test_older_shops_get_the_pictures_without_touching_what_an_owner_set(
    client, shop_a, shop_b, court
):
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.db.tenancy import mark_system
    from app.models import MenuItem
    from app.services.sample import add_sample_pictures

    with mark_system(SessionLocal()) as db:
        # make both shops look like they were set up before pictures existed...
        for item in db.scalars(select(MenuItem)):
            item.photo_url, item.description = "", ""
        # ...except one dish whose owner already gave it their own picture
        own = db.scalar(
            select(MenuItem).where(
                MenuItem.shop_id == shop_a.shop.id, MenuItem.name == "Masala tea"
            )
        )
        own.photo_url = "https://example.com/mine.jpg"
        db.commit()
        assert add_sample_pictures(db) == 3  # 4 sample dishes in two shops, minus the owner's own
        assert add_sample_pictures(db) == 0  # and running it again changes nothing
        db.refresh(own)
        assert own.photo_url == "https://example.com/mine.jpg" and own.description == ""
