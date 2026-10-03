"""Login and refresh-token rotation.

These run before we know the caller's shop, so they use a `system` session and
are written very carefully: every query is by an exact unique key.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.db.tenancy import mark_system
from app.models import RefreshToken, User
from app.schemas import TokenPair


class AuthError(Exception):
    pass


class LockedOut(AuthError):
    pass


# Five wrong passwords in a row lock the account for 15 minutes. Short on
# purpose: anyone who knows a cashier's number can trigger it, so a long lock
# would let them keep that cashier out of the till. The owner's reset clears it.
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)

# The few passwords people pick first. Not a full breached-password check (that
# needs a list download or an outside service); it stops the obvious ones.
_TOO_COMMON = {
    "12345678",
    "123456789",
    "1234567890",
    "87654321",
    "11111111",
    "00000000",
    "password",
    "password1",
    "qwertyui",
    "abcd1234",
    "chai1234",
    "tea12345",
}


def password_problem(password: str, phone: str) -> str | None:
    """Why this password is not acceptable, in plain words, or None."""
    if len(password) < 8:
        return "Use at least 8 characters"
    p = password.lower()
    if p in _TOO_COMMON or len(set(p)) < 3:
        return "That password is too easy to guess"
    if phone and phone in password:
        return "Do not use your phone number in the password"
    return None


def revoke_user_sessions(db: Session, user_id: uuid.UUID) -> None:
    """Log a person out everywhere (their refresh tokens stop working; an
    access token already issued lasts at most its few minutes)."""
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def _issue(db: Session, user: User, family_id: uuid.UUID) -> TokenPair:
    s = get_settings()
    raw, digest = new_refresh_token()
    now = datetime.now(UTC)
    db.add(
        RefreshToken(
            shop_id=user.shop_id,
            user_id=user.id,
            token_hash=digest,
            family_id=family_id,
            created_at=now,
            expires_at=now + timedelta(days=s.refresh_token_days),
        )
    )
    return TokenPair(
        access_token=create_access_token(user_id=user.id, shop_id=user.shop_id, role=user.role),
        refresh_token=raw,
        expires_in=s.access_token_minutes * 60,
    )


def login(db: Session, phone: str, password: str) -> TokenPair:
    mark_system(db)
    user = db.scalar(select(User).where(User.phone == phone).with_for_update())
    now = datetime.now(UTC)
    if user is not None and user.locked_until is not None and user.locked_until > now:
        minutes = max(1, -(-int((user.locked_until - now).total_seconds()) // 60))
        db.rollback()
        raise LockedOut(
            f"Too many wrong passwords. Try again in {minutes} minute"
            f"{'' if minutes == 1 else 's'}, or ask the owner to reset your password."
        )
    # verify_password runs even when user is None (constant-ish timing).
    ok = verify_password(password, user.password_hash if user else None)
    if user is not None and not ok:
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.failed_logins, user.locked_until = 0, now + LOCKOUT
        db.commit()
    if not ok or user is None or not user.is_active:
        db.rollback()
        raise AuthError("Invalid phone or password")
    user.failed_logins, user.locked_until = 0, None
    pair = _issue(db, user, family_id=uuid.uuid4())
    db.commit()
    return pair


def change_own_password(db: Session, user: User, current: str, new: str) -> TokenPair:
    """The person sets their own password. Every other session of theirs ends
    (a stolen phone stays logged in otherwise); this one gets fresh tokens."""
    if not verify_password(current, user.password_hash):
        raise AuthError("Your current password is not right")
    if new == current:
        raise AuthError("Choose a password different from the current one")
    problem = password_problem(new, user.phone)
    if problem:
        raise AuthError(problem)
    user.password_hash = hash_password(new)
    user.must_change_password = False
    user.failed_logins, user.locked_until = 0, None
    revoke_user_sessions(db, user.id)
    pair = _issue(db, user, family_id=uuid.uuid4())
    db.commit()
    return pair


def refresh(db: Session, raw_token: str) -> TokenPair:
    mark_system(db)
    now = datetime.now(UTC)
    token = db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(raw_token))
        .with_for_update()  # two concurrent refreshes of one token: only one wins
    )
    if token is None or token.expires_at <= now:
        raise AuthError("Invalid refresh token")

    if token.revoked_at is not None:
        # A token that was already rotated is being used again: either a bug or
        # a stolen token. Kill the whole family so the thief's copy dies too.
        _revoke_family(db, token.family_id, now)
        db.commit()
        raise AuthError("Refresh token reuse detected; please log in again")

    user = db.scalar(select(User).where(User.id == token.user_id))
    if user is None or not user.is_active:
        raise AuthError("Invalid refresh token")

    token.revoked_at = now
    pair = _issue(db, user, family_id=token.family_id)
    db.commit()
    return pair


def logout(db: Session, raw_token: str) -> None:
    mark_system(db)
    token = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
    )
    if token is not None:
        _revoke_family(db, token.family_id, datetime.now(UTC))
        db.commit()


def _revoke_family(db: Session, family_id: uuid.UUID, now: datetime) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
