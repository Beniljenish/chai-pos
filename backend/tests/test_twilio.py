"""Real SMS and WhatsApp through Twilio (README, "9.20"), over a stand-in connection: the request
Twilio would receive is checked, since the real service needs the owner's account."""

import httpx
import pytest

from app.core.config import get_settings
from app.services import messages, online, summary, twilio_sender
from tests.conftest import build_catalogue

API = "/api/v1"


class Fake:
    def __init__(self, status=201, body=None):
        self.calls, self.status, self.body = [], status, body or {"sid": "SM123"}

    def __call__(self, url, data, auth):
        self.calls.append((url, data, auth))
        return httpx.Response(self.status, json=self.body, request=httpx.Request("POST", url))


@pytest.fixture
def twilio(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "twilio_account_sid", "ACtest")
    monkeypatch.setattr(s, "twilio_auth_token", "token-for-tests")
    monkeypatch.setattr(s, "twilio_sms_from", "+19995550100")
    monkeypatch.setattr(s, "twilio_whatsapp_from", "+14155238886")
    fake = Fake()
    monkeypatch.setattr(twilio_sender, "_post", fake)
    return fake


def test_an_sms_goes_out_as_twilio_expects(twilio):
    assert twilio_sender.send("+919840012345", "hello") == "SM123"
    url, data, auth = twilio.calls[0]
    assert url == "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages.json"
    assert data == {"To": "+919840012345", "Body": "hello", "From": "+19995550100"}
    assert auth == ("ACtest", "token-for-tests")


def test_whatsapp_uses_the_whatsapp_prefix_and_a_messaging_service_its_own_field(
    twilio, monkeypatch
):
    twilio_sender.send("+919840012345", "hi", "whatsapp")
    assert twilio.calls[0][1] == {
        "To": "whatsapp:+919840012345",
        "Body": "hi",
        "From": "whatsapp:+14155238886",
    }
    monkeypatch.setattr(get_settings(), "twilio_sms_from", "MG0123456789")
    twilio_sender.send("+919840012345", "hi")
    assert (
        twilio.calls[1][1]["MessagingServiceSid"] == "MG0123456789"
        and "From" not in twilio.calls[1][1]
    )


def test_a_refusal_is_an_error_without_a_phone_number_in_it(twilio):
    twilio.status, twilio.body = 400, {"message": "The number +919840012345 is unverified"}
    with pytest.raises(twilio_sender.SendError) as e:
        twilio_sender.send("+919840012345", "x")
    assert "9840012345" not in str(e.value) and "[number]" in str(e.value)


def test_nothing_is_sent_when_it_is_not_set_up():
    with pytest.raises(twilio_sender.SendError):
        twilio_sender.send("+919840012345", "x")
    with pytest.raises(twilio_sender.SendError):
        twilio_sender.send("+919840012345", "x", "whatsapp")


def test_phone_codes_go_by_sms_and_are_asked_for_only_when_it_can(client, twilio):
    assert client.get(f"{API}/customer/verification").json() == {"required": True}
    r = client.post(f"{API}/customer/phone/code", json={"phone": "9840012345", "purpose": "signup"})
    assert (
        r.status_code == 200 and "dev_code" not in r.json()
    )  # the code goes to the phone, not the page
    body = twilio.calls[0][1]["Body"]
    code = next(w for w in body.split() if w.isdigit() and len(w) == 6)
    assert body.startswith("Taptallow:") and twilio.calls[0][1]["To"] == "+919840012345"
    # the code from the message creates the account
    ok = client.post(
        f"{API}/customer/signup",
        json={"name": "Ravi", "phone": "9840012345", "password": "ravi-secret-77", "code": code},
    )
    assert ok.status_code == 201, ok.text


def test_a_failed_send_says_so_and_does_not_pretend(client, twilio):
    twilio.status = 500
    r = client.post(f"{API}/customer/phone/code", json={"phone": "9840012345", "purpose": "signup"})
    assert r.status_code == 502 and r.json()["detail"]["code"] == "sms_failed"


def test_the_owners_summary_goes_by_whatsapp_when_it_is_set_up(client, shop_a, twilio):
    build_catalogue(client, shop_a)
    client.patch(
        f"{API}/shop",
        json={"summary_phone": "9840077777", "summary_on": True},
        headers=shop_a.owner_h,
    ).raise_for_status()
    with online.shop_session(shop_a.shop.id) as db:
        shop = db.get(type(shop_a.shop), shop_a.shop.id)
        assert summary.send(db, shop, __import__("datetime").date.today()) == "sent"
    _, data, _ = twilio.calls[0]
    assert data["To"] == "whatsapp:+919840077777" and data["Body"].startswith("Shop A")
    assert messages._override is None
