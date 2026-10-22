# ruff: noqa: F811  (fixtures imported from other test modules are used as arguments)
"""Round five, batch A (README, "9.21"): allergy tags, the change log, attendance and pay, price
history, special days, and deleting a customer account."""

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.time import business_date, utcnow
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from tests.conftest import PASSWORD, build_catalogue
from tests.test_food_court import API, _menu, _order, court  # noqa: F401


# ---------------------------------------------------------------- allergens and spice
def test_allergy_tags_and_spice_reach_the_customer_menu(client, shop_a, court):
    tea = next(
        m
        for m in client.get(f"{API}/menu-items", headers=shop_a.owner_h).json()
        if m["name"] == "Masala tea"
    )
    r = client.patch(
        f"{API}/menu-items/{tea['id']}",
        json={"allergens": ["milk", "nuts", "milk"], "spice_level": 1},
        headers=shop_a.owner_h,
    )
    assert r.status_code == 200, r.text
    assert (
        r.json()["allergens"] == ["nuts", "milk"] and r.json()["spice_level"] == 1
    )  # fixed order, no repeats
    item = _menu(client, court)["Masala tea"]
    assert item["allergens"] == ["nuts", "milk"] and item["spice_level"] == 1
    assert _menu(client, court)["Orange juice"]["allergens"] == []
    bad = client.patch(
        f"{API}/menu-items/{tea['id']}", json={"allergens": ["pollen"]}, headers=shop_a.owner_h
    )
    assert bad.status_code == 422
    assert (
        client.patch(
            f"{API}/menu-items/{tea['id']}", json={"spice_level": 9}, headers=shop_a.owner_h
        ).status_code
        == 422
    )
    # an edit that does not mention tags leaves them alone
    client.patch(
        f"{API}/menu-items/{tea['id']}", json={"description": "hot"}, headers=shop_a.owner_h
    )
    assert _menu(client, court)["Masala tea"]["allergens"] == ["nuts", "milk"]


# ---------------------------------------------------------------- the change log
def test_price_and_people_changes_are_logged_and_cannot_be_edited(client, shop_a):
    cat = build_catalogue(client, shop_a)
    h = shop_a.owner_h
    client.patch(
        f"{API}/menu-items/{cat.tea['id']}", json={"price_paise": 2200}, headers=h
    ).raise_for_status()
    client.patch(
        f"{API}/menu-items/{cat.tea['id']}", json={"description": "no money change"}, headers=h
    )
    client.put(
        f"{API}/menu-items/{cat.tea['id']}/recipe",
        json={"lines": [{"ingredient_id": cat.decoction["id"], "qty": "90"}]},
        headers=h,
    ).raise_for_status()
    client.patch(
        f"{API}/users/{shop_a.cashier.id}", json={"hourly_rate_paise": 5000}, headers=h
    ).raise_for_status()
    events = client.get(f"{API}/audit", headers=h).json()["events"]
    kinds = [(e["action"], e["subject"]) for e in events]
    assert ("menu_changed", "Masala tea") in kinds and ("recipe_changed", "Masala tea") in kinds
    assert ("pay_rate_changed", shop_a.cashier.name) in kinds
    price = next(e for e in events if e["action"] == "menu_changed")
    assert price["detail"] == {"field": "price_paise", "before": 2000, "after": 2200}
    assert price["who"] == shop_a.owner.name
    assert (
        sum(1 for e in events if e["action"] == "menu_changed") == 1
    )  # the description edit is not a money change
    assert client.get(f"{API}/audit", headers=shop_a.cashier_h).status_code == 403
    with mark_system(SessionLocal()) as db:  # even raw SQL cannot rewrite it
        with pytest.raises(Exception, match="append-only"):
            db.execute(text("UPDATE audit_events SET action = 'x'"))
        db.rollback()
        with pytest.raises(Exception, match="append-only"):
            db.execute(text("DELETE FROM audit_events"))


def test_a_failed_change_leaves_no_log_line(client, shop_a):
    before = len(client.get(f"{API}/audit", headers=shop_a.owner_h).json()["events"])
    r = client.patch(
        f"{API}/shop", json={"gst_type": "regular", "gstin": "bad"}, headers=shop_a.owner_h
    )
    assert r.status_code == 422
    assert len(client.get(f"{API}/audit", headers=shop_a.owner_h).json()["events"]) == before


# ---------------------------------------------------------------- attendance and pay
def test_clock_in_and_out_once_and_the_owner_sees_hours_and_pay(client, shop_a):
    c, o = shop_a.cashier_h, shop_a.owner_h
    assert client.post(f"{API}/attendance/out", headers=c).status_code == 409  # not in
    assert client.post(f"{API}/attendance/in", headers=c).status_code == 201
    assert client.post(f"{API}/attendance/in", headers=c).status_code == 409  # already in
    assert client.get(f"{API}/attendance/me", headers=c).json()["open"] is not None
    assert client.post(f"{API}/attendance/out", headers=c).status_code == 200
    assert client.get(f"{API}/attendance/me", headers=c).json()["open"] is None
    assert client.get(f"{API}/attendance", headers=c).status_code == 403
    rep = client.get(f"{API}/attendance", headers=o).json()
    (person,) = rep["people"]
    assert (
        person["name"] == shop_a.cashier.name
        and len(person["entries"]) == 1
        and person["pay_paise"] is None
    )


def test_pay_is_hours_times_rate_in_paise_and_corrections_are_logged(client, shop_a):
    c, o = shop_a.cashier_h, shop_a.owner_h
    client.post(f"{API}/attendance/in", headers=c).raise_for_status()
    client.post(f"{API}/attendance/out", headers=c).raise_for_status()
    entry = client.get(f"{API}/attendance", headers=o).json()["people"][0]["entries"][0]
    now = utcnow()
    start = (now - timedelta(hours=8, minutes=30)).isoformat()
    r = client.patch(
        f"{API}/attendance/{entry['id']}",
        json={"clock_in_at": start, "clock_out_at": now.isoformat(), "note": "forgot to tap"},
        headers=o,
    )
    assert r.status_code == 200 and r.json()["minutes"] == 510 and r.json()["edited"] is True
    client.patch(f"{API}/users/{shop_a.cashier.id}", json={"hourly_rate_paise": 12345}, headers=o)
    person = client.get(f"{API}/attendance", headers=o).json()["people"][0]
    assert (
        person["minutes"] == 510 and person["pay_paise"] == 104933
    )  # 8.5 h at ₹123.45: 104932.5 paise, half up
    bad = client.patch(
        f"{API}/attendance/{entry['id']}",
        json={"clock_in_at": now.isoformat(), "clock_out_at": start},
        headers=o,
    )
    assert bad.status_code == 422
    assert any(
        e["action"] == "attendance_corrected"
        for e in client.get(f"{API}/audit", headers=o).json()["events"]
    )


def test_an_open_entry_is_shown_but_not_counted(client, shop_a):
    client.post(f"{API}/attendance/in", headers=shop_a.cashier_h).raise_for_status()
    p = client.get(f"{API}/attendance", headers=shop_a.owner_h).json()["people"][0]
    assert p["still_in"] is True and p["minutes"] == 0


# ---------------------------------------------------------------- price history
def test_price_history_per_unit_and_the_change_against_the_average(client, shop_a):
    cat = build_catalogue(client, shop_a)
    h = shop_a.owner_h
    for paid in (500, 500, 500, 540):  # 1.2 litres each time
        client.post(
            f"{API}/stock-in",
            json={
                "ingredient_id": cat.milk["id"],
                "packs": [],
                "loose_qty": "1200",
                "cost_paise": paid,
            },
            headers=h,
        ).raise_for_status()
    hist = client.get(f"{API}/stock/{cat.milk['id']}/prices", headers=h).json()
    assert hist["per"] == "litre" and len(hist["entries"]) == 4
    assert hist["entries"][0]["price_paise"] == 450  # latest first: 540 paise for 1.2 litres
    summary = client.get(f"{API}/stock/prices", headers=h).json()["items"]
    milk = next(i for i in summary if i["name"] == "Milk")
    assert (
        milk["latest_paise"] == 450 and milk["change_pct"] == 7.9
    )  # against 417, the earlier average


# ---------------------------------------------------------------- special days
def test_special_days_look_back_at_last_year_and_suggest_fixed_holidays(client, shop_a):
    h = shop_a.owner_h
    build_catalogue(client, shop_a)
    today = business_date(utcnow())
    day = today + timedelta(days=20)
    got = client.post(
        f"{API}/special-days", json={"day": day.isoformat(), "name": "Diwali"}, headers=h
    ).json()
    (d,) = got["days"]
    assert d["name"] == "Diwali" and d["last_year_paise"] == 0 and d["usual_weekday_paise"] is None
    # adding the same one again changes nothing
    assert (
        len(
            client.post(
                f"{API}/special-days", json={"day": day.isoformat(), "name": "Diwali"}, headers=h
            ).json()["days"]
        )
        == 1
    )
    assert all(s["day"] >= today.isoformat() for s in got["suggestions"]) and got["suggestions"]
    gone = client.delete(f"{API}/special-days/{d['id']}", headers=h)
    assert gone.status_code == 200 and gone.json()["days"] == []
    assert client.get(f"{API}/special-days", headers=shop_a.cashier_h).status_code == 403


# ---------------------------------------------------------------- delete my account
def test_a_customer_can_erase_their_account_and_the_outlet_keeps_its_books(client, shop_a, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    _order(client, court, [(tea, 1)]).raise_for_status()
    who = court["customer"]
    client.put(f"{API}/customer/favourites/{tea}", headers=who).raise_for_status()
    wrong = client.post(
        f"{API}/customer/me/delete", json={"password": "not-my-password"}, headers=who
    )
    assert wrong.status_code == 403
    me = client.get(f"{API}/customer/me", headers=who).json()
    ok = client.post(f"{API}/customer/me/delete", json={"password": PASSWORD}, headers=who)
    assert ok.status_code == 200 and ok.json() == {"deleted": True}
    assert client.get(f"{API}/customer/me", headers=who).status_code == 401  # every token is dead
    login = client.post(f"{API}/customer/login", json={"phone": me["phone"], "password": PASSWORD})
    assert login.status_code == 401
    assert client.get(f"{API}/customer/favourites", headers=who).status_code == 401
    # the outlet still has its order
    assert len(client.get(f"{API}/orders/live", headers=shop_a.owner_h).json()["orders"]) == 1
