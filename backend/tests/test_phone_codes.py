"""Phone codes at sign-up, forgotten passwords reset by the customer, and the sign-up limit
(services/phone_codes.py, ratelimit.py). A stand-in sender catches the codes, as an SMS provider's
adapter would receive them."""

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.services import phone_codes

API = "/api/v1"
PHONE = "9841055555"
PASS = "tea-and-biscuits-77"


@pytest.fixture
def sms():
    sent = []
    phone_codes.set_sender(lambda phone, purpose, code: sent.append((phone, purpose, code)))
    yield sent
    phone_codes.set_sender(None)


def _sql(sql, **p):
    db = mark_system(SessionLocal())
    try:
        db.execute(text(sql), p)
        db.commit()
    finally:
        db.close()


def _code(client, sent, purpose="signup", phone=PHONE):
    r = client.post(f"{API}/customer/phone/code", json={"phone": phone, "purpose": purpose})
    assert r.status_code == 200, r.text
    return sent[-1][2]


def _signup(client, code="", phone=PHONE, headers=None):
    body = {"name": "Ravi", "phone": phone, "password": PASS, "code": code}
    return client.post(f"{API}/customer/signup", json=body, headers=headers or {})


def test_with_no_sms_sender_nothing_asks_for_a_code_and_signup_is_as_before(client):
    assert client.get(f"{API}/customer/verification").json() == {"required": False}
    assert _signup(client).status_code == 201
    r = client.post(f"{API}/customer/phone/code", json={"phone": PHONE, "purpose": "signup"})
    assert r.status_code == 503


def test_signup_needs_the_code_sent_to_that_number(client, sms):
    assert client.get(f"{API}/customer/verification").json() == {"required": True}
    missing = _signup(client)
    assert missing.status_code == 422 and missing.json()["detail"]["code"] == "code_required"
    code = _code(client, sms)
    assert len(code) == 6 and code.isdigit() and sms[-1][:2] == (PHONE, "signup")
    wrong = _signup(client, code="000000" if code != "000000" else "111111")
    assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "code_wrong"
    ok = _signup(client, code=code)
    assert ok.status_code == 201 and ok.json()["account"]["phone"] == PHONE
    # the code worked once
    again = _signup(client, code=code, phone="9841066666")
    assert again.status_code == 422  # it was for another number and is used up


def test_a_code_for_another_number_or_purpose_does_not_work(client, sms):
    code = _code(client, sms, phone="9841011111")
    r = _signup(client, code=code, phone="9841022222")
    assert r.status_code == 422
    reset = client.post(
        f"{API}/customer/password/reset",
        json={"phone": "9841011111", "code": code, "new_password": "another-pass-9876"},
    )
    assert reset.status_code == 422  # a sign-up code cannot reset a password


def test_codes_expire_and_lock_after_five_wrong_tries(client, sms):
    code = _code(client, sms)
    _sql("UPDATE phone_codes SET expires_at = now() - interval '1 minute'")
    gone = _signup(client, code=code)
    assert gone.status_code == 422 and gone.json()["detail"]["code"] == "code_expired"

    _sql("DELETE FROM phone_codes")
    _sql("DELETE FROM rate_hits")
    code = _code(client, sms)
    bad = "000000" if code != "000000" else "111111"
    for _ in range(phone_codes.MAX_ATTEMPTS):
        assert _signup(client, code=bad).json()["detail"]["code"] == "code_wrong"
    locked = _signup(client, code=code)  # even the right one, now
    assert locked.status_code == 429 and locked.json()["detail"]["code"] == "code_locked"


def test_codes_are_not_sent_too_often(client, sms):
    _code(client, sms)
    soon = client.post(f"{API}/customer/phone/code", json={"phone": PHONE, "purpose": "signup"})
    assert soon.status_code == 429 and soon.json()["detail"]["code"] == "too_soon"
    for _ in range(phone_codes.SENDS_PER_HOUR - 1):
        _sql("UPDATE phone_codes SET created_at = now() - interval '5 minutes'")
        assert (
            client.post(
                f"{API}/customer/phone/code", json={"phone": PHONE, "purpose": "signup"}
            ).status_code
            == 200
        )
    _sql("UPDATE phone_codes SET created_at = now() - interval '5 minutes'")
    capped = client.post(f"{API}/customer/phone/code", json={"phone": PHONE, "purpose": "signup"})
    assert capped.status_code == 429 and capped.json()["detail"]["code"] == "too_many"


def test_a_customer_resets_their_own_password_with_a_code(client, sms):
    # an account made while codes were off
    phone_codes.set_sender(None)
    assert _signup(client).status_code == 201
    phone_codes.set_sender(lambda phone, purpose, code: sms.append((phone, purpose, code)))
    old = client.post(f"{API}/customer/login", json={"phone": PHONE, "password": PASS}).json()
    code = _code(client, sms, purpose="reset")
    r = client.post(
        f"{API}/customer/password/reset",
        json={"phone": PHONE, "code": code, "new_password": "brand-new-pass-4321"},
    )
    assert r.status_code == 200 and r.json()["account"]["phone"] == PHONE
    # the old password and the old login both stop working
    stale = client.get(
        f"{API}/customer/me", headers={"Authorization": f"Bearer {old['access_token']}"}
    )
    assert stale.status_code == 401
    assert (
        client.post(f"{API}/customer/login", json={"phone": PHONE, "password": PASS}).status_code
        == 401
    )
    fresh = client.post(
        f"{API}/customer/login", json={"phone": PHONE, "password": "brand-new-pass-4321"}
    )
    assert fresh.status_code == 200
    # a weak new password is refused and does not burn the code
    code2 = _code_after_wait(client, sms)
    weak = client.post(
        f"{API}/customer/password/reset",
        json={"phone": PHONE, "code": code2, "new_password": "12345678"},
    )
    assert weak.status_code == 422


def _code_after_wait(client, sms):
    _sql("UPDATE phone_codes SET created_at = now() - interval '5 minutes'")
    return _code(client, sms, purpose="reset")


def test_forgot_password_does_not_reveal_who_has_an_account(client, sms):
    known = client.post(f"{API}/customer/phone/code", json={"phone": PHONE, "purpose": "reset"})
    assert known.status_code == 200 and known.json()["sent"] is True
    assert sms == []  # no account: nothing was sent, and the answer was the same
    assert (
        client.post(
            f"{API}/customer/password/reset",
            json={"phone": PHONE, "code": "123456", "new_password": "brand-new-pass-4321"},
        ).json()["detail"]["code"]
        == "code_wrong"
    )


def test_signups_from_one_address_are_limited(client, monkeypatch):
    from app.services import customer_accounts

    monkeypatch.setattr(customer_accounts, "SIGNUPS_PER_HOUR", 3)
    hdr = {"x-forwarded-for": "203.0.113.9, 10.0.0.1"}
    for n in range(3):
        assert _signup(client, phone=f"98410777{n:02d}", headers=hdr).status_code == 201
    blocked = _signup(client, phone="9841077799", headers=hdr)
    assert blocked.status_code == 429 and blocked.json()["detail"]["code"] == "too_many_signups"
    other = _signup(client, phone="9841077798", headers={"x-forwarded-for": "198.51.100.4"})
    assert other.status_code == 201


def test_the_pretend_sms_mode_shows_the_code_and_refuses_a_real_database(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "fake_sms", True)
    r = client.post(f"{API}/customer/phone/code", json={"phone": PHONE, "purpose": "signup"})
    code = r.json()["dev_code"]
    assert _signup(client, code=code).status_code == 201

    from app.core.config import Settings

    with pytest.raises(ValueError, match="FAKE_SMS"):
        Settings(
            fake_sms=True,
            database_url="postgresql+psycopg://u:p@db.example.com:5432/x",
            jwt_secret="x" * 40,
        )
