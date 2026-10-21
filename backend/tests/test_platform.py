"""The super admin (services/platform.py): who can reach the admin routes, what they can do
with food courts and outlets, and that the admin and shop worlds never mix."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import FoodCourtOutlet, PlatformAdmin
from app.services import auth as auth_service
from scripts import new_platform_admin
from tests.conftest import PASSWORD, PLATFORM_PHONE, build_catalogue, platform_headers

API = "/api/v1"


@pytest.fixture
def admin(client):
    return platform_headers(client)


def _courts(client, admin):
    r = client.get(f"{API}/platform/courts", headers=admin)
    assert r.status_code == 200, r.text
    return {c["name"]: c for c in r.json()["courts"]}


def _make_court(client, admin, name="Marina Food Court"):
    r = client.post(f"{API}/platform/courts", json={"name": name}, headers=admin)
    assert r.status_code == 201, r.text
    return next(c for c in r.json()["courts"] if c["name"] == name)


# ---------------------------------------------------------------- signing in
def test_the_admin_signs_in_and_a_wrong_password_does_not(client, admin):
    ok = client.post(f"{API}/platform/login", json={"phone": PLATFORM_PHONE, "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["name"] == "Test admin"
    bad = client.post(
        f"{API}/platform/login", json={"phone": PLATFORM_PHONE, "password": "nope-nope"}
    )
    unknown = client.post(
        f"{API}/platform/login", json={"phone": "9999999999", "password": PASSWORD}
    )
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()  # a wrong number looks like a wrong password


def test_repeated_wrong_passwords_lock_the_admin_for_a_while(client, admin):
    for _ in range(auth_service.MAX_FAILED_LOGINS):
        client.post(
            f"{API}/platform/login", json={"phone": PLATFORM_PHONE, "password": "nope-nope"}
        )
    right = client.post(
        f"{API}/platform/login", json={"phone": PLATFORM_PHONE, "password": PASSWORD}
    )
    assert right.status_code == 429


def test_local_test_mode_signs_in_by_phone_for_a_real_admin_only(client, admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "dev_login", True)
    assert (
        client.post(
            f"{API}/platform/login", json={"phone": PLATFORM_PHONE, "password": "-"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{API}/platform/login", json={"phone": "9999999999", "password": "-"}
        ).status_code
        == 401
    )


def test_a_switched_off_admin_is_out_at_once(client, admin):
    assert client.get(f"{API}/platform/me", headers=admin).status_code == 200
    with mark_system(SessionLocal()) as db:
        db.scalar(select(PlatformAdmin)).is_active = False
        db.commit()
    assert client.get(f"{API}/platform/me", headers=admin).status_code == 401


# ---------------------------------------------------------------- the two worlds never mix
def test_a_shop_login_cannot_use_the_admin_routes(client, admin, shop_a):
    for method, path, body in (
        ("GET", "/platform/me", None),
        ("GET", "/platform/courts", None),
        ("POST", "/platform/courts", {"name": "Hijack"}),
    ):
        r = client.request(method, f"{API}{path}", json=body, headers=shop_a.owner_h)
        assert r.status_code == 401, (path, r.status_code)
    assert client.get(f"{API}/platform/courts").status_code == 401
    assert _courts(client, admin) == {}


def test_an_admin_login_cannot_use_a_shops_routes(client, admin, shop_a):
    for path in (
        "/food-court",
        "/shop",
        "/catalogue",
        "/users",
        "/orders/live",
        "/auth/me",
        "/stock",
    ):
        assert client.get(f"{API}{path}", headers=admin).status_code == 401, path


# ---------------------------------------------------------------- food courts
def test_the_admin_makes_a_court_and_lists_it(client, admin):
    court = _make_court(client, admin)
    assert court["outlets"] == [] and court["slug"].startswith("marina-food-court-")
    assert set(_courts(client, admin)) == {"Marina Food Court"}
    assert (
        client.post(f"{API}/platform/courts", json={"name": "x"}, headers=admin).status_code == 422
    )


def test_a_new_outlet_gets_a_shop_an_owner_login_and_a_menu(client, admin):
    court = _make_court(client, admin)
    r = client.post(
        f"{API}/platform/courts/{court['id']}/outlets",
        json={
            "shop_name": "Anna Biryani",
            "owner_name": "Anna",
            "owner_phone": "98411 00000",
            "password": "temp-pass-123",
            "sample_menu": True,
        },
        headers=admin,
    )
    assert r.status_code == 201, r.text
    (outlet,) = _courts(client, admin)["Marina Food Court"]["outlets"]
    assert outlet["name"] == "Anna Biryani" and outlet["owner_phone"] == "9841100000"
    assert outlet["owner_name"] == "Anna" and outlet["accepting_orders"] is False

    # the owner signs in with the temporary password and must choose their own
    tokens = client.post(
        f"{API}/auth/login", json={"phone": "9841100000", "password": "temp-pass-123"}
    )
    assert tokens.status_code == 200
    h = {"Authorization": f"Bearer {tokens.json()['access_token']}"}
    assert client.get(f"{API}/auth/me", headers=h).json()["must_change_password"] is True
    # and the outlet is a shop of its own, with the sample menu, in the court
    pub = client.get(f"{API}/public/courts/{court['slug']}").json()
    menu = client.get(
        f"{API}/public/courts/{court['slug']}/outlets/{pub['outlets'][0]['id']}/menu"
    ).json()
    assert {i["name"] for i in menu["items"]} == {"Masala tea", "Orange juice"}


def test_a_new_outlet_is_refused_for_a_taken_number_a_weak_password_or_no_court(
    client, admin, shop_a
):
    court = _make_court(client, admin)
    url = f"{API}/platform/courts/{court['id']}/outlets"
    body = {"shop_name": "Copycat", "owner_phone": shop_a.owner.phone}
    taken = client.post(url, json=body, headers=admin)
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "cannot_create"
    weak = client.post(
        url, json={**body, "owner_phone": "9841100001", "password": "12345678"}, headers=admin
    )
    assert weak.status_code == 422 and weak.json()["detail"]["code"] == "weak_password"
    lost = client.post(
        f"{API}/platform/courts/{uuid.uuid4()}/outlets",
        json={**body, "owner_phone": "9841100002"},
        headers=admin,
    )
    assert lost.status_code == 404
    assert _courts(client, admin)["Marina Food Court"]["outlets"] == []  # nothing half-made


def test_an_existing_shop_is_attached_by_its_owners_number(client, admin, shop_a, shop_b):
    court = _make_court(client, admin)
    url = f"{API}/platform/courts/{court['id']}/outlets/attach"
    assert (
        client.post(url, json={"owner_phone": shop_a.owner.phone}, headers=admin).status_code == 201
    )
    again = client.post(url, json={"owner_phone": shop_a.owner.phone}, headers=admin)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_in_a_court"
    # a cashier's number is not an owner's, and an unknown number is nobody's
    assert (
        client.post(url, json={"owner_phone": shop_b.cashier.phone}, headers=admin).status_code
        == 404
    )
    assert client.post(url, json={"owner_phone": "9999999999"}, headers=admin).status_code == 404
    assert client.post(url, json={"owner_phone": "12345"}, headers=admin).status_code == 422
    (o,) = _courts(client, admin)["Marina Food Court"]["outlets"]
    assert o["name"] == shop_a.shop.name and o["owner_phone"] == shop_a.owner.phone


def test_the_admin_can_close_an_outlet_and_its_owner_can_open_it_again(client, admin, shop_a):
    court = _make_court(client, admin)
    client.post(
        f"{API}/platform/courts/{court['id']}/outlets/attach",
        json={"owner_phone": shop_a.owner.phone},
        headers=admin,
    ).raise_for_status()
    (outlet,) = _courts(client, admin)["Marina Food Court"]["outlets"]
    one = f"{API}/platform/courts/{court['id']}/outlets/{outlet['id']}"
    client.patch(one, json={"accepting_orders": True}, headers=admin).raise_for_status()
    pub = lambda: client.get(f"{API}/public/courts/{court['slug']}").json()["outlets"][0]["open"]  # noqa: E731
    assert pub() is True
    client.patch(one, json={"accepting_orders": False}, headers=admin).raise_for_status()
    assert pub() is False
    r = client.patch(
        f"{API}/food-court/me", json={"accepting_orders": True}, headers=shop_a.owner_h
    )
    assert r.status_code == 200 and pub() is True


def test_removing_an_outlet_takes_it_out_of_the_court_and_nothing_else(client, admin, shop_a):
    build_catalogue(client, shop_a)
    court = _make_court(client, admin)
    client.post(
        f"{API}/platform/courts/{court['id']}/outlets/attach",
        json={"owner_phone": shop_a.owner.phone},
        headers=admin,
    ).raise_for_status()
    (outlet,) = _courts(client, admin)["Marina Food Court"]["outlets"]
    r = client.delete(f"{API}/platform/courts/{court['id']}/outlets/{outlet['id']}", headers=admin)
    assert r.status_code == 200
    assert _courts(client, admin)["Marina Food Court"]["outlets"] == []
    assert client.get(f"{API}/public/courts/{court['slug']}").json()["outlets"] == []
    assert client.get(f"{API}/food-court", headers=shop_a.owner_h).json() == {"court": None}
    # the shop itself, its menu and its login are untouched
    assert client.get(f"{API}/catalogue", headers=shop_a.owner_h).status_code == 200
    with mark_system(SessionLocal()) as db:
        assert db.scalars(select(FoodCourtOutlet)).all() == []


def test_an_outlet_id_from_another_court_is_not_found(client, admin, shop_a, shop_b):
    one, two = _make_court(client, admin, "One"), _make_court(client, admin, "Two")
    client.post(
        f"{API}/platform/courts/{one['id']}/outlets/attach",
        json={"owner_phone": shop_a.owner.phone},
        headers=admin,
    ).raise_for_status()
    (theirs,) = _courts(client, admin)["One"]["outlets"]
    wrong = f"{API}/platform/courts/{two['id']}/outlets/{theirs['id']}"
    assert client.patch(wrong, json={"accepting_orders": True}, headers=admin).status_code == 404
    assert client.delete(wrong, headers=admin).status_code == 404
    assert len(_courts(client, admin)["One"]["outlets"]) == 1


# ---------------------------------------------------------------- how an admin is made
def test_the_script_makes_an_admin_once_and_asks_for_what_it_needs(monkeypatch, capsys):
    monkeypatch.delenv("NEW_ADMIN_PHONE", raising=False)
    with pytest.raises(SystemExit, match="NEW_ADMIN_PHONE"):
        new_platform_admin.main()
    monkeypatch.setenv("NEW_ADMIN_PHONE", "98400 00001")
    monkeypatch.setenv("NEW_ADMIN_PASSWORD", "short")
    with pytest.raises(SystemExit, match="8 characters"):
        new_platform_admin.main()
    monkeypatch.setenv("NEW_ADMIN_PASSWORD", "a-long-password-1")
    new_platform_admin.main()
    new_platform_admin.main()  # again: nothing to do, no second row
    out = capsys.readouterr().out
    assert "Created super admin" in out and "already a super admin" in out
    with mark_system(SessionLocal()) as db:
        assert len(db.scalars(select(PlatformAdmin)).all()) == 1
