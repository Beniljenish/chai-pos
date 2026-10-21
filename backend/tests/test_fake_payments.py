# ruff: noqa: F811  (fixtures imported from other test modules are used as arguments)
"""FAKE_PAYMENTS: pretend online payment for local testing. Off unless asked for, refused against
anything but a local database, and it never turns on the till's own Razorpay payment."""

import uuid

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from tests.test_food_court import API, court  # noqa: F401
from tests.test_online_payments import TWO, _start, _status

SECRET = "x" * 40
LOCAL = "postgresql+psycopg://chai:chai@localhost:5432/chai_pos"
REMOTE = (
    "postgresql+psycopg://postgres.abc:pw@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres"
)


def test_off_by_default_nothing_is_offered_and_the_local_route_does_not_exist(client, court):
    assert client.get(f"{API}/public/courts/{court['slug']}").json()["online_payment"] is False
    r = client.post(f"{API}/payments/razorpay/local-pay", json={"order_id": "order_L100xabcd1234"})
    assert r.status_code == 404
    assert _start(client, court, TWO).status_code == 503


def test_on_a_customer_can_pay_with_pretend_money_and_get_tokens(client, court, monkeypatch):
    monkeypatch.setattr(get_settings(), "fake_payments", True)
    assert client.get(f"{API}/public/courts/{court['slug']}").json()["online_payment"] is True
    started = _start(client, court, TWO).json()
    assert started["razorpay_order_id"].startswith("order_L")
    page = client.get(
        f"{API}/payments/razorpay/customer-checkout?order_id={started['razorpay_order_id']}"
    )
    assert page.status_code == 200
    assert "pretend money" in page.text and "checkout.razorpay.com" not in page.text

    paid = client.post(
        f"{API}/payments/razorpay/local-pay", json={"order_id": started["razorpay_order_id"]}
    )
    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    done = _status(client, court, started["id"]).json()
    assert done["fulfilled"] is True and all(o["token"] for o in done["orders"])
    assert sum(o["amount_paise"] for o in done["orders"]) == started["amount_paise"]
    # paying twice changes nothing
    again = client.post(
        f"{API}/payments/razorpay/local-pay", json={"order_id": started["razorpay_order_id"]}
    )
    assert again.status_code == 200
    assert _status(client, court, started["id"]).json()["orders"] == done["orders"]


def test_the_tills_own_online_payment_stays_off(client, shop_a, monkeypatch):
    from tests.conftest import FakeDevice, build_catalogue

    monkeypatch.setattr(get_settings(), "fake_payments", True)
    build_catalogue(client, shop_a)
    assert FakeDevice(client, shop_a).catalogue["shop"]["online_payments"] is False


def test_an_unknown_order_is_not_found(client, court, monkeypatch):
    monkeypatch.setattr(get_settings(), "fake_payments", True)
    r = client.post(
        f"{API}/payments/razorpay/local-pay", json={"order_id": f"order_L1x{uuid.uuid4().hex[:8]}"}
    )
    assert r.status_code == 404


@pytest.mark.parametrize("url", [LOCAL, LOCAL.replace("localhost", "db")])
def test_allowed_with_a_database_on_this_computer(url):
    assert Settings(jwt_secret=SECRET, database_url=url, fake_payments=True).fake_payments


@pytest.mark.parametrize(
    "kwargs",
    [{"database_url": REMOTE}, {"database_url": LOCAL, "env": "prod"}],
)
def test_refused_against_a_remote_database_or_in_production(kwargs):
    with pytest.raises(ValidationError, match="FAKE_PAYMENTS"):
        Settings(jwt_secret=SECRET, fake_payments=True, **kwargs)
