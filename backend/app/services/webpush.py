"""Web Push, written out (RFC 8030 delivery, RFC 8291 message encryption, RFC 8292 VAPID).

Why not the `pywebpush` package: it needs `http-ece`, which does not build everywhere (it did not
here), and a build that fails on the server is a bad way to lose notifications. The protocol is
short; `cryptography` does the maths and `httpx` the posting. `tests/test_webpush.py` decrypts a
message the way a phone does, so the encryption is proved, not assumed.

Keys: VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY (see `python -m scripts.make_vapid_keys`). With either
missing, push is off and nothing here is called.
"""

import base64
import logging
import os
import struct
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings

log = logging.getLogger(__name__)

RECORD_SIZE = 4096
MAX_PAYLOAD = 3500  # one record, with room for padding and the tag


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def enabled() -> bool:
    s = get_settings()
    return bool(s.vapid_public_key.strip() and s.vapid_private_key.strip())


def public_key() -> str | None:
    return get_settings().vapid_public_key.strip() or None if enabled() else None


def generate_keys() -> tuple[str, str]:
    """A new VAPID key pair as (public, private), both URL-safe base64: the public key is the
    65-byte point the browser is given, the private key the 32-byte secret."""
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return b64u(public), b64u(private)


def encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    """The message body for one browser (RFC 8291, `aes128gcm`): salt, record size, our one-time
    public key, then the single encrypted record."""
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload too large")
    ua_public = b64d(p256dh)
    auth_secret = b64d(auth)
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    as_public = ephemeral.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    shared = ephemeral.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    )
    salt = os.urandom(16)
    ikm = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=auth_secret,
        info=b"WebPush: info\x00" + ua_public + as_public,
    ).derive(shared)
    cek = HKDF(
        algorithm=hashes.SHA256(), length=16, salt=salt, info=b"Content-Encoding: aes128gcm\x00"
    ).derive(ikm)
    nonce = HKDF(
        algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00"
    ).derive(ikm)
    record = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # 0x02: the last (only) record
    return salt + struct.pack(">IB", RECORD_SIZE, len(as_public)) + as_public + record


def vapid_authorization(endpoint: str) -> str:
    """The `Authorization` header that tells the push service who is sending (RFC 8292)."""
    s = get_settings()
    parts = urlsplit(endpoint)
    private = ec.derive_private_key(
        int.from_bytes(b64d(s.vapid_private_key.strip()), "big"), ec.SECP256R1()
    )
    token = jwt.encode(
        {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int(time.time()) + 12 * 3600,
            "sub": s.vapid_subject,
        },
        private,
        algorithm="ES256",
    )
    return f"vapid t={token}, k={s.vapid_public_key.strip()}"


Sender = Callable[[str, bytes, dict[str, str]], int]
_sender: Sender | None = None


def set_sender(sender: Sender | None) -> None:
    """Tests give a stand-in that records what would have been posted."""
    global _sender
    _sender = sender


def _post(endpoint: str, body: bytes, headers: dict[str, str]) -> int:
    if _sender is not None:
        return _sender(endpoint, body, headers)
    return httpx.post(endpoint, content=body, headers=headers, timeout=4).status_code


def send(endpoint: str, p256dh: str, auth: str, message: dict, ttl: int = 3600) -> str:
    """Send one notification. Returns "ok", "gone" (the browser forgot the subscription: delete
    it) or "error" (try again later, or not at all). Never raises: a missed notification must not
    break the kitchen's screen."""
    import json

    try:
        body = encrypt(json.dumps(message).encode(), p256dh, auth)
        status = _post(
            endpoint,
            body,
            {
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(ttl),
                "Urgency": "high",
                "Authorization": vapid_authorization(endpoint),
            },
        )
    except Exception:  # noqa: BLE001 - see the docstring
        log.warning("web push to %s failed", urlsplit(endpoint).netloc)
        return "error"
    if status in (404, 410):
        return "gone"
    return "ok" if 200 <= status < 300 else "error"
