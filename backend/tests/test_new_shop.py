"""scripts.new_shop: how a second outlet's shop and owner login are made (there is no sign-up)."""

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import Device, MenuItem, Role, Shop
from scripts import new_shop

API = "/api/v1"


def test_a_new_shop_gets_an_owner_who_must_choose_their_own_password(client):
    shop, owner = new_shop.create_shop("Anna Biryani", "98411 00000", "Anna", "temp-pass-123")
    assert shop.name == "Anna Biryani" and shop.invoice_prefix == "AB"
    assert owner.phone == "9841100000" and owner.role == Role.owner and owner.must_change_password
    # the temporary password works, and until it is replaced nothing else does
    tokens = client.post(
        f"{API}/auth/login", json={"phone": "9841100000", "password": "temp-pass-123"}
    )
    assert tokens.status_code == 200
    h = {"Authorization": f"Bearer {tokens.json()['access_token']}"}
    assert client.get(f"{API}/auth/me", headers=h).json()["must_change_password"] is True
    assert client.get(f"{API}/shop", headers=h).status_code == 403
    with mark_system(SessionLocal()) as db:
        assert db.scalar(select(Device.code).where(Device.shop_id == shop.id)) == "C1"


def test_without_a_password_nobody_knows_one(client):
    _, owner = new_shop.create_shop("Dosa Dhaba", "9841100001")
    assert not owner.must_change_password
    assert (
        client.post(
            f"{API}/auth/login", json={"phone": "9841100001", "password": "guess-guess"}
        ).status_code
        == 401
    )


def test_a_number_that_already_has_a_login_is_refused(client, shop_a):
    with pytest.raises(ValueError, match="already has a login"):
        new_shop.create_shop("Copycat", shop_a.owner.phone)
    with pytest.raises(ValueError):
        new_shop.create_shop("Bad number", "12345")


def test_the_new_shop_is_separate_and_can_have_the_sample_menu(client, shop_a, monkeypatch):
    shop, owner = new_shop.create_shop("Fresh Juice Bar", "9841100002", password="temp-pass-123")
    monkeypatch.setenv("SAMPLE_MENU", "1")
    from scripts import seed

    seed.seed_catalogue(shop, owner)
    with mark_system(SessionLocal()) as db:
        names = set(db.scalars(select(MenuItem.name).where(MenuItem.shop_id == shop.id)))
        other = set(db.scalars(select(MenuItem.name).where(MenuItem.shop_id == shop_a.shop.id)))
        assert db.scalar(select(Shop.id).where(Shop.name == "Fresh Juice Bar")) == shop.id
    assert (
        names == {"Masala tea", "Orange juice"} and other == set()
    )  # shop_a has no menu of its own here


def test_the_script_asks_for_what_it_needs(monkeypatch):
    monkeypatch.delenv("NEW_SHOP_NAME", raising=False)
    monkeypatch.delenv("NEW_OWNER_PHONE", raising=False)
    with pytest.raises(SystemExit, match="NEW_SHOP_NAME"):
        new_shop.main()
    monkeypatch.setenv("NEW_SHOP_NAME", "Anna Biryani")
    monkeypatch.setenv("NEW_OWNER_PHONE", "9841100003")
    monkeypatch.setenv("NEW_OWNER_PASSWORD", "short")
    with pytest.raises(SystemExit, match="8 characters"):
        new_shop.main()
