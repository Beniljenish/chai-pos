"""The super admin's API (README, "9.12"). Every route but the login needs a platform token."""

import uuid
from dataclasses import dataclass

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.v1.foodcourt import fail, system_db
from app.core.security import decode_platform_token
from app.models import PlatformAdmin
from app.schemas import _normalise_phone
from app.services import auth as auth_service
from app.services import customer_accounts as customer_service
from app.services import online
from app.services import platform as platform_service

router = APIRouter(prefix="/platform", tags=["platform"])
_bearer = HTTPBearer(auto_error=False)
_UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
)


@dataclass(frozen=True)
class Admin:
    admin: PlatformAdmin
    db: Session


def current_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(system_db),
) -> Admin:
    """Only a platform token passes: a shop user's token has the wrong type."""
    if creds is None:
        raise _UNAUTHORIZED
    try:
        admin_id = decode_platform_token(creds.credentials)
    except (jwt.PyJWTError, ValueError, KeyError):
        raise _UNAUTHORIZED from None
    admin = db.get(PlatformAdmin, admin_id)
    if admin is None or not admin.is_active:  # switched off: effective at once, not at expiry
        raise _UNAUTHORIZED
    return Admin(admin, db)


class LoginIn(BaseModel):
    phone: str
    password: str = Field(min_length=1, max_length=128)

    _phone = field_validator("phone")(_normalise_phone)


class CourtIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    location: str = Field(default="", max_length=120)


class NewOutletIn(BaseModel):
    shop_name: str = Field(min_length=2, max_length=120)
    owner_name: str = Field(default="Owner", max_length=120)
    owner_phone: str
    password: str | None = Field(default=None, max_length=128)
    sample_menu: bool = False


class AttachIn(BaseModel):
    owner_phone: str


class ResetIn(BaseModel):
    phone: str

    _phone = field_validator("phone")(_normalise_phone)


class AcceptingIn(BaseModel):
    accepting_orders: bool


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(system_db)) -> dict:
    try:
        token, admin = platform_service.login(db, body.phone, body.password)
    except auth_service.LockedOut as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e)) from None
    except auth_service.AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from None
    return {"access_token": token, "name": admin.name}


@router.get("/me")
def me(a: Admin = Depends(current_admin)) -> dict:
    return {"name": a.admin.name, "phone": a.admin.phone}


@router.get("/courts")
def courts(a: Admin = Depends(current_admin)) -> dict:
    return {"courts": platform_service.list_courts(a.db)}


def _run(fn, *args):
    try:
        return fn(*args)
    except online.OnlineError as e:
        raise fail(e) from None


@router.post("/courts", status_code=201)
def create_court(body: CourtIn, a: Admin = Depends(current_admin)) -> dict:
    platform_service.create_court(a.db, a.admin.id, body.name, body.location)
    return {"courts": platform_service.list_courts(a.db)}


@router.post("/courts/{court_id}/outlets", status_code=201)
def add_outlet(court_id: uuid.UUID, body: NewOutletIn, a: Admin = Depends(current_admin)) -> dict:
    _run(
        platform_service.add_new_outlet,
        a.db,
        court_id,
        body.shop_name,
        body.owner_name,
        body.owner_phone,
        body.password or None,
        body.sample_menu,
    )
    return {"courts": platform_service.list_courts(a.db)}


@router.post("/courts/{court_id}/outlets/attach", status_code=201)
def attach_outlet(court_id: uuid.UUID, body: AttachIn, a: Admin = Depends(current_admin)) -> dict:
    _run(platform_service.attach_outlet, a.db, court_id, body.owner_phone)
    return {"courts": platform_service.list_courts(a.db)}


@router.patch("/courts/{court_id}/outlets/{outlet_id}")
def set_accepting(
    court_id: uuid.UUID,
    outlet_id: uuid.UUID,
    body: AcceptingIn,
    a: Admin = Depends(current_admin),
) -> dict:
    _run(platform_service.set_outlet_accepting, a.db, court_id, outlet_id, body.accepting_orders)
    return {"courts": platform_service.list_courts(a.db)}


@router.delete("/courts/{court_id}/outlets/{outlet_id}")
def remove_outlet(
    court_id: uuid.UUID, outlet_id: uuid.UUID, a: Admin = Depends(current_admin)
) -> dict:
    _run(platform_service.remove_outlet, a.db, court_id, outlet_id)
    return {"courts": platform_service.list_courts(a.db)}


@router.post("/customers/reset-password")
def reset_customer_password(body: ResetIn, a: Admin = Depends(current_admin)) -> dict:
    """A customer forgot their password. Returns a temporary one, once, for the admin to
    tell them; they must choose their own at the next sign-in."""
    return _run(customer_service.admin_reset, a.db, body.phone)
