"""DEV_LOGIN: phone-only login for local testing. Off unless asked for, and the
settings refuse it against anything but a database on this computer."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings

API = "/api/v1"
SECRET = "x" * 40
LOCAL = "postgresql+psycopg://chai:chai@localhost:5432/chai_pos"
REMOTE = (
    "postgresql+psycopg://postgres.abc:pw@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres"
)


def _login(client, phone, password="not the password"):
    return client.post(f"{API}/auth/login", json={"phone": phone, "password": password})


def test_off_by_default_a_wrong_password_is_refused(client, shop_a):
    assert client.get(f"{API}/auth/dev-login").json() == {"enabled": False}
    assert _login(client, shop_a.owner.phone).status_code == 401


def test_on_a_known_phone_gets_in_without_the_password(client, shop_a, monkeypatch):
    monkeypatch.setattr(get_settings(), "dev_login", True)
    assert client.get(f"{API}/auth/dev-login").json() == {"enabled": True}
    r = _login(client, shop_a.owner.phone)
    assert r.status_code == 200 and r.json()["access_token"]
    # the token is the real thing: it opens the owner's records
    me = client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
    )
    assert me.status_code == 200 and me.json()["role"] == "owner"


def test_on_an_unknown_phone_is_still_refused(client, shop_a, monkeypatch):
    monkeypatch.setattr(get_settings(), "dev_login", True)
    assert _login(client, "9999999999").status_code == 401


def test_on_a_switched_off_user_is_still_refused(client, shop_a, monkeypatch):
    from sqlalchemy import update

    from app.db.session import SessionLocal
    from app.db.tenancy import mark_system
    from app.models import User

    with SessionLocal() as db:
        mark_system(db).execute(
            update(User).where(User.id == shop_a.cashier.id).values(is_active=False)
        )
        db.commit()
    monkeypatch.setattr(get_settings(), "dev_login", True)
    assert _login(client, shop_a.cashier.phone).status_code == 401


@pytest.mark.parametrize(
    "url", [LOCAL, LOCAL.replace("localhost", "db"), LOCAL.replace("localhost", "127.0.0.1")]
)
def test_settings_allow_it_with_a_local_database(url):
    assert Settings(_env_file=None, jwt_secret=SECRET, dev_login=True, database_url=url).dev_login


def test_settings_refuse_it_against_a_remote_database():
    with pytest.raises(ValidationError, match="DEV_LOGIN"):
        Settings(_env_file=None, jwt_secret=SECRET, dev_login=True, database_url=REMOTE)


def test_settings_refuse_it_in_prod_even_with_a_local_database():
    with pytest.raises(ValidationError, match="DEV_LOGIN"):
        Settings(_env_file=None, jwt_secret=SECRET, dev_login=True, env="prod", database_url=LOCAL)
