"""Request-level dependencies: who is calling, which shop, which role."""

import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.db.tenancy import bind_tenant
from app.models import Role, User

_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


@dataclass(frozen=True)
class TenantContext:
    shop_id: uuid.UUID
    user_id: uuid.UUID
    role: Role


@dataclass(frozen=True)
class Caller:
    ctx: TenantContext
    db: Session  # already bound to ctx.shop_id
    user: User


def get_caller_even_if_password_pending(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Caller:
    """Only for /auth/me and /auth/password: what a person with an owner-set
    password may still do. Every other route uses get_caller."""
    if creds is None:
        raise _UNAUTHORIZED
    try:
        payload = decode_access_token(creds.credentials)
        shop_id = uuid.UUID(payload["shop"])
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError):
        raise _UNAUTHORIZED from None

    # shop_id comes ONLY from the signed token, never from the request.
    bind_tenant(db, shop_id)

    # Re-check the user on every request: a deactivated cashier or a role
    # change takes effect immediately, not when the 15-minute token expires.
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    return Caller(ctx=TenantContext(shop_id, user.id, user.role), db=db, user=user)


def get_caller(caller: Caller = Depends(get_caller_even_if_password_pending)) -> Caller:
    # The owner set this password, so the owner knows it: until the person picks
    # their own, nothing they do could be told apart from the owner doing it.
    if caller.user.must_change_password:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "password_change_required", "message": "Set your own password first"},
        )
    return caller


def require_owner(caller: Caller = Depends(get_caller)) -> Caller:
    if caller.ctx.role != Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owner role required")
    return caller
