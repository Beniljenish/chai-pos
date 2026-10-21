# ruff: noqa: F811  (fixtures imported from other test modules are used as arguments)
"""Web Push (services/webpush.py): the encryption is proved by decrypting a message the way a
phone does, and the "ready" notice goes out once, to the right customer, and only when set up."""

import json
import struct
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import OnlineOrder, PushSubscription
from app.services import webpush
from tests.conftest import customer_headers
from tests.test_food_court import API, _events, _live, _menu, _order, court  # noqa: F401


class Phone:
    """A browser's side of a push subscription: it holds the private key and auth secret."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.public = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        self.auth = b"0123456789abcdef"

    @property
    def p256dh(self) -> str:
        return webpush.b64u(self.public)

    @property
    def auth_b64(self) -> str:
        return webpush.b64u(self.auth)

    def decrypt(self, body: bytes) -> bytes:
        """RFC 8291, from the receiver's side."""
        salt = body[:16]
        rs, idlen = struct.unpack(">IB", body[16:21])
        as_public = body[21 : 21 + idlen]
        record = body[21 + idlen :]
        assert rs == 4096 and idlen == 65
        shared = self.key.exchange(
            ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
        )
        ikm = HKDF(
            hashes.SHA256(), 32, self.auth, b"WebPush: info\x00" + self.public + as_public
        ).derive(shared)
        cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
        nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
        plain = AESGCM(cek).decrypt(nonce, record, None)
        assert plain[-1] == 2  # the delimiter of the last record
        return plain[:-1]


@pytest.fixture
def keys(monkeypatch):
    public, private = webpush.generate_keys()
    s = get_settings()
    monkeypatch.setattr(s, "vapid_public_key", public)
    monkeypatch.setattr(s, "vapid_private_key", private)
    monkeypatch.setattr(s, "vapid_subject", "mailto:test@example.com")
    return public


class Posted(list):
    """What the stand-in push service received, plus the status code it answers with."""

    code = 201


@pytest.fixture
def posted():
    sent = Posted()

    def sender(endpoint, body, headers):
        sent.append((endpoint, body, headers))
        return sent.code

    webpush.set_sender(sender)
    yield sent
    webpush.set_sender(None)


def test_a_message_decrypts_on_the_phone_and_only_there(keys, posted):
    phone = Phone()
    message = {"title": "JT-17 is ready to collect", "body": "Jolly Tiffins · counter ₹"}
    assert (
        webpush.send("https://push.example.net/abc", phone.p256dh, phone.auth_b64, message) == "ok"
    )
    endpoint, body, headers = posted[0]
    assert endpoint == "https://push.example.net/abc"
    assert json.loads(phone.decrypt(body)) == message
    assert b"JT-17" not in body  # what travels is encrypted
    assert headers["Content-Encoding"] == "aes128gcm" and headers["TTL"] == "3600"
    # a second message is encrypted afresh: new salt, new one-time key
    webpush.send("https://push.example.net/abc", phone.p256dh, phone.auth_b64, message)
    assert posted[1][1][:16] != body[:16] and posted[1][1][21:86] != body[21:86]
    # another phone cannot read it
    other = Phone()
    with pytest.raises(Exception):  # noqa: B017,PT011 - any decryption failure will do
        other.decrypt(body)


def test_the_vapid_header_is_signed_for_the_push_service_and_checks_out(keys, posted):
    phone = Phone()
    webpush.send("https://push.example.net/abc", phone.p256dh, phone.auth_b64, {"t": 1})
    header = posted[0][2]["Authorization"]
    token = header.split("t=")[1].split(",")[0]
    assert header.endswith(f"k={keys}")
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), webpush.b64d(keys))
    claims = jwt.decode(token, public, algorithms=["ES256"], audience="https://push.example.net")
    assert claims["sub"] == "mailto:test@example.com" and claims["exp"] > 0


def test_gone_and_failed_deliveries_are_told_apart_and_never_raise(keys, posted):
    phone = Phone()
    args = ("https://push.example.net/x", phone.p256dh, phone.auth_b64, {"t": 1})
    posted.code = 410
    assert webpush.send(*args) == "gone"
    posted.code = 500
    assert webpush.send(*args) == "error"
    assert webpush.send("https://push.example.net/x", "not-a-key", "x", {"t": 1}) == "error"


def test_push_is_off_without_both_keys(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "vapid_public_key", "abc")
    monkeypatch.setattr(s, "vapid_private_key", "")
    assert webpush.enabled() is False and webpush.public_key() is None


def _subscribe(client, who, endpoint="https://push.example.net/phone1", phone=None):
    phone = phone or Phone()
    r = client.post(
        f"{API}/customer/push/subscribe",
        json={"endpoint": endpoint, "keys": {"p256dh": phone.p256dh, "auth": phone.auth_b64}},
        headers=who,
    )
    return r, phone


def test_subscribing_needs_an_account_and_a_set_up_server(client, court, keys):
    body = {
        "endpoint": "https://push.example.net/p",
        "keys": {"p256dh": "x" * 30, "auth": "y" * 12},
    }
    assert client.post(f"{API}/customer/push/subscribe", json=body).status_code == 401
    assert client.get(f"{API}/customer/push/key", headers=court["customer"]).json() == {
        "public_key": keys
    }
    r, _ = _subscribe(client, court["customer"])
    assert r.status_code == 201
    bad = client.post(
        f"{API}/customer/push/subscribe",
        json={**body, "endpoint": "http://insecure.example/p"},
        headers=court["customer"],
    )
    assert bad.status_code == 422


def test_subscribing_is_refused_when_push_is_not_set_up(client, court, monkeypatch):
    monkeypatch.setattr(get_settings(), "vapid_private_key", "")
    assert client.get(f"{API}/customer/push/key", headers=court["customer"]).json() == {
        "public_key": None
    }
    r, _ = _subscribe(client, court["customer"])
    assert r.status_code == 503 and r.json()["detail"]["code"] == "push_off"


def test_the_same_phone_twice_is_one_subscription_and_can_be_removed(client, court, keys):
    phone = Phone()
    _subscribe(client, court["customer"], phone=phone)
    _subscribe(client, court["customer"], phone=phone)
    with mark_system(SessionLocal()) as db:
        assert len(db.scalars(select(PushSubscription)).all()) == 1
    r = client.post(
        f"{API}/customer/push/unsubscribe",
        json={"endpoint": "https://push.example.net/phone1"},
        headers=court["customer"],
    )
    assert r.status_code == 200
    with mark_system(SessionLocal()) as db:
        assert db.scalars(select(PushSubscription)).all() == []


def _make_ready(client, shop, order_id):
    order = next(o for o in _live(client, shop) if o["id"] == order_id)
    lines = [ln["line_id"] for ln in order["state"]["lines"]]
    _events(client, shop, order_id, [("ready", {"line_ids": lines})])


def test_the_customers_phone_is_told_once_when_everything_is_ready(
    client, shop_a, court, keys, posted
):
    r, phone = _subscribe(client, court["customer"])
    assert r.status_code == 201
    menu = _menu(client, court)
    placed = _order(
        client, court, [(menu["Masala tea"]["id"], 1), (menu["Orange juice"]["id"], 1)]
    ).json()
    order = next(o for o in _live(client, shop_a) if o["id"] == placed["order_id"])
    first, second = [ln["line_id"] for ln in order["state"]["lines"]]
    _events(client, shop_a, placed["order_id"], [("ready", {"line_ids": [first]})])
    assert posted == []  # half the order is not ready yet
    _events(client, shop_a, placed["order_id"], [("ready", {"line_ids": [second]})])
    assert len(posted) == 1
    message = json.loads(phone.decrypt(posted[0][1]))
    assert message["title"] == f"{placed['token']} is ready to collect"
    assert shop_a.shop.name in message["body"] and message["url"] == f"/order/{court['slug']}"
    # the same news again changes nothing
    _events(client, shop_a, placed["order_id"], [("ready", {"line_ids": [first, second]})])
    assert len(posted) == 1
    with mark_system(SessionLocal()) as db:
        assert db.scalar(select(OnlineOrder.ready_notified_at)) is not None


def test_only_the_customer_who_ordered_is_told(client, shop_a, court, keys, posted):
    _, mine = _subscribe(client, court["customer"], "https://push.example.net/mine")
    other = customer_headers(client, "9841100000", "Priya")
    _, theirs = _subscribe(client, other, "https://push.example.net/theirs")
    placed = _order(client, court, [(_menu(client, court)["Masala tea"]["id"], 1)]).json()
    _make_ready(client, shop_a, placed["order_id"])
    assert [p[0] for p in posted] == ["https://push.example.net/mine"]
    assert theirs is not mine


def test_a_phone_that_forgot_us_is_dropped_and_a_dead_push_service_breaks_nothing(
    client, shop_a, court, keys, posted
):
    _subscribe(client, court["customer"])
    posted.code = 410
    placed = _order(client, court, [(_menu(client, court)["Masala tea"]["id"], 1)]).json()
    _make_ready(client, shop_a, placed["order_id"])
    with mark_system(SessionLocal()) as db:
        assert db.scalars(select(PushSubscription)).all() == []
    # the kitchen's own screen still sees the order as ready: the notice never got in its way
    order = next(o for o in _live(client, shop_a) if o["id"] == placed["order_id"])
    assert all(ln["ready"] for ln in order["state"]["lines"])


def test_a_counter_order_with_no_push_set_up_just_works(client, shop_a, court, posted):
    placed = _order(client, court, [(_menu(client, court)["Masala tea"]["id"], 1)]).json()
    _make_ready(client, shop_a, placed["order_id"])
    assert posted == []
    assert uuid.UUID(placed["order_id"])
