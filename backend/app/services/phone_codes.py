"""Proving a mobile number with a code (README, "9.17"): a check at sign-up, and a way for a
customer to reset their own forgotten password so nobody has to ring the super admin.

The code is 6 digits, kept only as a hash, valid 10 minutes, wrong 5 times kills it, and it works
once. At most 5 are sent to a number an hour, and 30 seconds apart. Sending goes through one seam
(`set_sender`): locally (FAKE_SMS) the code is handed back to the page, in production a real SMS
provider's adapter goes here. With neither, verification is OFF and sign-up works as before: a
number is a login name, not a verified fact.
"""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import PhoneCode
from app.services import ratelimit, twilio_sender
from app.services.online import OnlineError

TTL = timedelta(minutes=10)
COOLDOWN = timedelta(seconds=30)
MAX_ATTEMPTS = 5
SENDS_PER_HOUR = 5
PURPOSES = ("signup", "reset")

Sender = Callable[[str, str, str], None]  # (phone, purpose, code)
_sender: Sender | None = None


def set_sender(fn: Sender | None) -> None:
    """A real SMS adapter goes here (and tests put theirs here); None removes it."""
    global _sender
    _sender = fn


def fake_on() -> bool:
    return get_settings().fake_sms and _sender is None


def available() -> bool:
    """Whether codes can be sent at all. When they cannot, nothing asks for one."""
    return _sender is not None or get_settings().fake_sms or twilio_sender.sms_on()


def _hash(phone: str, purpose: str, code: str) -> str:
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"{phone}:{purpose}:{code}".encode(), hashlib.sha256).hexdigest()


def send(db: Session, phone: str, purpose: str) -> dict:
    """Make and send a code. Returns what the page may show: the cooldown, and in local test mode
    the code itself. Raises OnlineError when it is too soon or too many."""
    if purpose not in PURPOSES:
        raise OnlineError("bad_purpose", "Unknown purpose", 422)
    if not available():
        raise OnlineError("sms_off", "Phone codes are not switched on", 503)
    now = datetime.now(UTC)
    last = db.scalar(
        select(PhoneCode)
        .where(PhoneCode.phone == phone, PhoneCode.purpose == purpose)
        .order_by(PhoneCode.created_at.desc())
        .limit(1)
    )
    if last is not None and now - last.created_at < COOLDOWN:
        wait = int((COOLDOWN - (now - last.created_at)).total_seconds()) + 1
        raise OnlineError("too_soon", f"Wait {wait} seconds before asking for another code.", 429)
    try:
        ratelimit.hit(
            db,
            f"code:{phone}",
            limit=SENDS_PER_HOUR,
            window=timedelta(hours=1),
            message="Too many codes were sent to this number. Try again in an hour.",
        )
    except ratelimit.RateLimited as e:
        db.rollback()
        raise OnlineError("too_many", e.message, 429) from None
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(
        PhoneCode(
            phone=phone,
            purpose=purpose,
            code_hash=_hash(phone, purpose, code),
            expires_at=now + TTL,
        )
    )
    db.commit()
    if _sender is not None:
        _sender(phone, purpose, code)
    elif not fake_on() and twilio_sender.sms_on():
        try:
            twilio_sender.send(
                f"+91{phone}",
                f"Taptallow: {code} is your code. It works for 10 minutes. Do not share it.",
            )
        except twilio_sender.SendError:
            raise OnlineError(
                "sms_failed", "We could not send the code. Please try again in a minute.", 502
            ) from None
    out: dict = {"sent": True, "cooldown_seconds": int(COOLDOWN.total_seconds())}
    if fake_on():
        out["dev_code"] = (
            code  # local testing only: config refuses FAKE_SMS against a remote database
        )
    return out


def check(db: Session, phone: str, purpose: str, code: str) -> None:
    """Use up the number's latest code if `code` is right. Raises OnlineError otherwise. The caller
    commits (a wrong try is committed here so it counts even if the caller then rolls back)."""
    row = db.scalar(
        select(PhoneCode)
        .where(PhoneCode.phone == phone, PhoneCode.purpose == purpose, PhoneCode.used_at.is_(None))
        .order_by(PhoneCode.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    now = datetime.now(UTC)
    if row is None or row.expires_at < now:
        db.rollback()
        raise OnlineError("code_expired", "That code has expired. Ask for a new one.", 422)
    if row.attempts >= MAX_ATTEMPTS:
        db.rollback()
        raise OnlineError("code_locked", "Too many wrong tries. Ask for a new code.", 429)
    if not hmac.compare_digest(row.code_hash, _hash(phone, purpose, code.strip())):
        row.attempts += 1
        db.commit()
        raise OnlineError("code_wrong", "That code is not right.", 422)
    row.used_at = now
    db.flush()
