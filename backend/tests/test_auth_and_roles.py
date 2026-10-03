from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient

from app.core.config import get_settings
from tests.conftest import PASSWORD, ShopFixture


def _login(client, phone, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"phone": phone, "password": password})


def test_login_and_me(client: TestClient, shop_a: ShopFixture):
    r = client.get("/api/v1/auth/me", headers=shop_a.cashier_h)
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "cashier" and "password_hash" not in body


def test_login_accepts_plus91_format(client, shop_a):
    assert _login(client, "+91 " + shop_a.owner.phone).status_code == 200


def test_wrong_password_and_unknown_phone_look_identical(client, shop_a):
    a = _login(client, shop_a.owner.phone, "wrong-password")
    b = _login(client, "9999999999", "wrong-password")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_deactivated_user_is_locked_out_immediately(client, shop_a):
    r = client.patch(
        f"/api/v1/users/{shop_a.cashier.id}", json={"is_active": False}, headers=shop_a.owner_h
    )
    assert r.status_code == 200
    # the cashier's still-unexpired access token stops working at once
    assert client.get("/api/v1/auth/me", headers=shop_a.cashier_h).status_code == 401
    assert _login(client, shop_a.cashier.phone).status_code == 401


def test_owner_cannot_deactivate_self(client, shop_a):
    r = client.patch(
        f"/api/v1/users/{shop_a.owner.id}", json={"is_active": False}, headers=shop_a.owner_h
    )
    assert r.status_code == 400


def test_missing_tampered_and_alg_none_tokens_rejected(client, shop_a):
    assert client.get("/api/v1/auth/me").status_code == 401
    tampered = shop_a.owner_token[:-4] + "AAAA"
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered}"}).status_code
        == 401
    )
    payload = jwt.decode(shop_a.owner_token, options={"verify_signature": False})
    none_tok = jwt.encode(payload, key=None, algorithm="none")
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {none_tok}"}).status_code
        == 401
    )


def test_expired_token_rejected(client, shop_a):
    s = get_settings()
    payload = jwt.decode(shop_a.owner_token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    payload["exp"] = datetime.now(UTC) - timedelta(seconds=1)
    old = jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    )


def test_refresh_rotates_and_detects_reuse(client, shop_a):
    first = _login(client, shop_a.owner.phone).json()
    second = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    assert second.json()["refresh_token"] != first["refresh_token"]

    # replaying the old token = suspected theft -> 401 and the family is killed
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401
    killed = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second.json()["refresh_token"]}
    )
    assert killed.status_code == 401


def test_logout_revokes_refresh_token(client, shop_a):
    tokens = _login(client, shop_a.owner.phone).json()
    assert (
        client.post(
            "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 204
    )
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


def test_cashier_cannot_use_owner_endpoints(client, shop_a):
    h = shop_a.cashier_h
    assert client.get("/api/v1/users", headers=h).status_code == 403
    assert client.post("/api/v1/devices", json={"name": "x"}, headers=h).status_code == 403
    assert client.patch("/api/v1/shop", json={"name": "x"}, headers=h).status_code == 403
    # but cashiers can see devices (billing screen needs its own device code)
    assert client.get("/api/v1/devices", headers=h).status_code == 200


def test_owner_creates_cashier_who_can_log_in(client, shop_a):
    r = client.post(
        "/api/v1/users",
        json={"name": "New", "phone": "8123456789", "password": "longenough1"},
        headers=shop_a.owner_h,
    )
    assert r.status_code == 201 and r.json()["role"] == "cashier"
    assert _login(client, "8123456789", "longenough1").status_code == 200
    dup = client.post(
        "/api/v1/users",
        json={"name": "Dup", "phone": "8123456789", "password": "longenough1"},
        headers=shop_a.owner_h,
    )
    assert dup.status_code == 409


def test_device_codes_increment_per_shop(client, shop_a, shop_b):
    r = client.post("/api/v1/devices", json={"name": "Counter 2"}, headers=shop_a.owner_h)
    assert r.json()["code"] == "C2"
    r = client.post("/api/v1/devices", json={"name": "Counter 2"}, headers=shop_b.owner_h)
    assert r.json()["code"] == "C2"


def test_validation_rejects_bad_phone_and_gstin(client, shop_a):
    r = client.post(
        "/api/v1/users",
        json={"name": "x", "phone": "12345", "password": "longenough1"},
        headers=shop_a.owner_h,
    )
    assert r.status_code == 422
    r = client.patch("/api/v1/shop", json={"gstin": "NOTAGSTIN"}, headers=shop_a.owner_h)
    assert r.status_code == 422
    # Lower case is tidied; the last character is a real check digit (Z7, not Z5).
    ok = client.patch("/api/v1/shop", json={"gstin": "33abcde1234f1z7"}, headers=shop_a.owner_h)
    assert ok.status_code == 200 and ok.json()["gstin"] == "33ABCDE1234F1Z7"


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
