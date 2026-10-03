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
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.db.tenancy import mark_system
from app.models import RefreshToken, User
from app.schemas import TokenPair


class AuthError(Exception):
    pass


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
    user = db.scalar(select(User).where(User.phone == phone))
    # verify_password runs even when user is None (constant-ish timing).
    ok = verify_password(password, user.password_hash if user else None)
    if not ok or user is None or not user.is_active:
        raise AuthError("Invalid phone or password")
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
