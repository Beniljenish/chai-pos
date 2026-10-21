import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

_hasher = PasswordHasher()
# Verified against when the phone number is unknown, so a wrong phone and a
# wrong password take the same time (prevents user enumeration by timing).
_DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(*, user_id: uuid.UUID, shop_id: uuid.UUID, role: str) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "shop": str(shop_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=s.access_token_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    s = get_settings()
    # Pinning algorithms= blocks the classic "alg: none" / algorithm-swap attacks.
    payload = jwt.decode(
        token,
        s.jwt_secret,
        algorithms=[s.jwt_algorithm],
        options={"require": ["exp", "sub", "shop", "role", "type"]},
    )
    if payload["type"] != "access":
        raise jwt.InvalidTokenError("not an access token")
    return payload


PLATFORM_TOKEN_HOURS = 8


def create_platform_token(admin_id: uuid.UUID) -> str:
    """A super admin's token. It has no shop and no role, and a different `type`, so
    every shop route (which requires a shop and type "access") refuses it."""
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(admin_id),
        "type": "platform",
        "iat": now,
        "exp": now + timedelta(hours=PLATFORM_TOKEN_HOURS),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_platform_token(token: str) -> uuid.UUID:
    s = get_settings()
    payload = jwt.decode(
        token,
        s.jwt_secret,
        algorithms=[s.jwt_algorithm],
        options={"require": ["exp", "sub", "type"]},
    )
    if payload["type"] != "platform":
        raise jwt.InvalidTokenError("not a platform token")
    return uuid.UUID(payload["sub"])


def new_refresh_token() -> tuple[str, str]:
    """Returns (raw token for the client, sha256 hash to store)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    # SHA-256 (not argon2) is right here: the token is 48 random bytes, so it
    # cannot be brute-forced, and we need an exact-match lookup by hash.
    return hashlib.sha256(raw.encode()).hexdigest()
