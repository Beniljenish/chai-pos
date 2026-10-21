"""A food-court customer's own account (README, "9.13").

Every route but sign-up and log-in needs a customer token, and only a customer token
passes: a shop user's or the super admin's has the wrong type.
"""

from dataclasses import dataclass

import jwt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.v1.foodcourt import fail, system_db
from app.core.security import decode_customer_token
from app.models import CustomerAccount
from app.schemas import _normalise_phone
from app.services import auth as auth_service
from app.services import customer_accounts, online

router = APIRouter(prefix="/customer", tags=["customer"])
_bearer = HTTPBearer(auto_error=False)
_UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
)


@dataclass(frozen=True)
class Customer:
    account: CustomerAccount
    db: Session


def current_customer(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(system_db),
) -> Customer:
    if creds is None:
        raise _UNAUTHORIZED
    try:
        customer_id, version = decode_customer_token(creds.credentials)
    except (jwt.PyJWTError, ValueError, KeyError):
        raise _UNAUTHORIZED from None
    account = db.get(CustomerAccount, customer_id)
    # Switched off, or the password changed since this token was issued: effective at once.
    if account is None or not account.is_active or account.token_version != version:
        raise _UNAUTHORIZED
    return Customer(account, db)


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    phone: str
    password: str = Field(min_length=1, max_length=128)

    _phone = field_validator("phone")(_normalise_phone)


class LoginIn(BaseModel):
    phone: str
    password: str = Field(min_length=1, max_length=128)

    _phone = field_validator("phone")(_normalise_phone)


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class RenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.post("/signup", status_code=201)
def signup(body: SignupIn, response: Response, db: Session = Depends(system_db)) -> dict:
    _no_store(response)
    try:
        return customer_accounts.signup(db, body.name, body.phone, body.password)
    except online.OnlineError as e:
        raise fail(e) from None


@router.post("/login")
def login(body: LoginIn, response: Response, db: Session = Depends(system_db)) -> dict:
    _no_store(response)
    try:
        return customer_accounts.login(db, body.phone, body.password)
    except auth_service.LockedOut as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e)) from None
    except auth_service.AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from None


@router.get("/me")
def me(response: Response, c: Customer = Depends(current_customer)) -> dict:
    _no_store(response)
    return customer_accounts.account_view(c.account)


@router.patch("/me")
def rename(body: RenameIn, c: Customer = Depends(current_customer)) -> dict:
    try:
        return customer_accounts.rename(c.db, c.account, body.name)
    except online.OnlineError as e:
        raise fail(e) from None


@router.post("/password")
def change_password(body: PasswordIn, c: Customer = Depends(current_customer)) -> dict:
    try:
        return customer_accounts.change_password(
            c.db, c.account, body.current_password, body.new_password
        )
    except online.OnlineError as e:
        raise fail(e) from None


@router.get("/orders")
def orders(response: Response, c: Customer = Depends(current_customer)) -> dict:
    _no_store(response)
    return {"orders": customer_accounts.history(c.db, c.account.id)}
