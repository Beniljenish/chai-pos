"""A food-court customer's own account (README, "9.13").

Every route but sign-up and log-in needs a customer token, and only a customer token
passes: a shop user's or the super admin's has the wrong type.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.v1.foodcourt import fail, system_db
from app.core.security import decode_customer_token
from app.models import CustomerAccount, OnlinePayment
from app.schemas import _normalise_phone
from app.services import auth as auth_service
from app.services import customer_accounts, extras, online, onlinepay, phone_codes, webpush

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
    code: str = Field(default="", max_length=10)  # the phone code, when codes are switched on

    _phone = field_validator("phone")(_normalise_phone)


class LoginIn(BaseModel):
    phone: str
    password: str = Field(min_length=1, max_length=128)

    _phone = field_validator("phone")(_normalise_phone)


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class CheckoutItemIn(BaseModel):
    menu_item_id: uuid.UUID
    qty: int = Field(ge=1, le=online.MAX_QTY)
    modifier_ids: list[uuid.UUID] = Field(default_factory=list, max_length=6)


class CheckoutPartIn(BaseModel):
    outlet_id: uuid.UUID
    request_id: uuid.UUID  # one per outlet's order, made by the page
    note: str = Field(default="", max_length=120)
    pickup_at: datetime | None = None
    table_name: str = Field(default="", max_length=20)
    items: list[CheckoutItemIn] = Field(min_length=1, max_length=online.MAX_LINES)


class CheckoutIn(BaseModel):
    checkout_id: uuid.UUID  # made by the page: a second tap is the same payment
    slug: str = Field(max_length=60)
    message_ok: bool = False
    orders: list[CheckoutPartIn] = Field(min_length=1, max_length=onlinepay.MAX_OUTLETS)


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class PushSubscribeIn(BaseModel):
    endpoint: str = Field(min_length=20, max_length=600, pattern=r"^https://")
    keys: PushKeys


class PushEndpointIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=600)


class RatingIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=200)


class RenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def client_ip(request: Request) -> str:
    """The caller's address: the first hop the host's proxy reports, else the socket's."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host if request.client else ""


class CodeIn(BaseModel):
    phone: str
    purpose: str = Field(pattern="^(signup|reset)$")

    _phone = field_validator("phone")(_normalise_phone)


class ResetIn(BaseModel):
    phone: str
    code: str = Field(min_length=1, max_length=10)
    new_password: str = Field(min_length=1, max_length=128)

    _phone = field_validator("phone")(_normalise_phone)


@router.get("/verification")
def verification(response: Response) -> dict:
    """Whether the page should ask for a phone code at sign-up (it cannot if none can be sent)."""
    _no_store(response)
    return {"required": phone_codes.available()}


@router.post("/phone/code")
def send_code(body: CodeIn, response: Response, db: Session = Depends(system_db)) -> dict:
    _no_store(response)
    try:
        if body.purpose == "reset":
            return customer_accounts.forgot(db, body.phone)
        return phone_codes.send(db, body.phone, "signup")
    except online.OnlineError as e:
        raise fail(e) from None


@router.post("/password/reset")
def reset_password(body: ResetIn, response: Response, db: Session = Depends(system_db)) -> dict:
    _no_store(response)
    try:
        return customer_accounts.reset_with_code(db, body.phone, body.code, body.new_password)
    except online.OnlineError as e:
        raise fail(e) from None


@router.post("/signup", status_code=201)
def signup(
    body: SignupIn, request: Request, response: Response, db: Session = Depends(system_db)
) -> dict:
    _no_store(response)
    try:
        return customer_accounts.signup(
            db, body.name, body.phone, body.password, body.code, client_ip(request)
        )
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


@router.get("/usual")
def usual(
    outlet_id: uuid.UUID, response: Response, c: Customer = Depends(current_customer)
) -> dict:
    """The dishes this customer usually orders at one outlet (README, "9.18")."""
    _no_store(response)
    return {"usual": customer_accounts.usual(c.db, c.account.id, outlet_id)}


@router.post("/checkout", status_code=201)
def checkout(body: CheckoutIn, response: Response, c: Customer = Depends(current_customer)) -> dict:
    """Open an online payment for a cart (one or more outlets of one food court). Nothing is
    sent to a kitchen yet: that happens when the payment is confirmed."""
    _no_store(response)
    try:
        op = onlinepay.start(
            c.db,
            c.account,
            body.slug,
            body.checkout_id,
            [
                onlinepay.PartIn(
                    outlet_id=o.outlet_id,
                    request_id=o.request_id,
                    note=o.note,
                    pickup_at=o.pickup_at,
                    table_name=o.table_name,
                    items=[
                        online.Pick(i.menu_item_id, i.qty, tuple(i.modifier_ids)) for i in o.items
                    ],
                )
                for o in body.orders
            ],
            body.message_ok,
        )
        return onlinepay.view(op)
    except online.OnlineError as e:
        raise fail(e) from None


@router.get("/checkout/{checkout_id}")
def checkout_status(
    checkout_id: uuid.UUID, response: Response, c: Customer = Depends(current_customer)
) -> dict:
    """Where a payment stands. Once it is paid this also finishes the job (places the orders),
    so a customer who closed the page can open it again and get their tokens."""
    _no_store(response)
    op = c.db.get(OnlinePayment, checkout_id)
    if op is None or op.customer_id != c.account.id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": "not_found", "message": "No such payment"}
        )
    try:
        if op.status == "paid" and op.fulfilled_at is None:
            onlinepay.fulfil(c.db, op)
        return onlinepay.view(op)
    except online.OnlineError as e:
        raise fail(e) from None


# ---------------------------------------------------------------- phone notifications
@router.get("/push/key")
def push_key(response: Response, c: Customer = Depends(current_customer)) -> dict:
    """The public key a browser needs to subscribe, or null when push is not set up."""
    _no_store(response)
    return {"public_key": webpush.public_key()}


@router.post("/push/subscribe", status_code=201)
def push_subscribe(body: PushSubscribeIn, c: Customer = Depends(current_customer)) -> dict:
    if not webpush.enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "push_off", "message": "Notifications are not set up"},
        )
    extras.subscribe(c.db, c.account, body.endpoint, body.keys.p256dh, body.keys.auth)
    return {"ok": True}


@router.post("/push/unsubscribe")
def push_unsubscribe(body: PushEndpointIn, c: Customer = Depends(current_customer)) -> dict:
    extras.unsubscribe(c.db, c.account, body.endpoint)
    return {"ok": True}


# ---------------------------------------------------------------- favourites
@router.get("/favourites")
def favourites(response: Response, c: Customer = Depends(current_customer)) -> dict:
    _no_store(response)
    return {"favourites": extras.favourites(c.db, c.account.id)}


@router.put("/favourites/{menu_item_id}")
def add_favourite(menu_item_id: uuid.UUID, c: Customer = Depends(current_customer)) -> dict:
    try:
        extras.add_favourite(c.db, c.account.id, menu_item_id)
    except online.OnlineError as e:
        raise fail(e) from None
    return {"favourites": extras.favourites(c.db, c.account.id)}


@router.delete("/favourites/{menu_item_id}")
def remove_favourite(menu_item_id: uuid.UUID, c: Customer = Depends(current_customer)) -> dict:
    extras.remove_favourite(c.db, c.account.id, menu_item_id)
    return {"favourites": extras.favourites(c.db, c.account.id)}


# ---------------------------------------------------------------- rating a collected order
@router.get("/orders/{status_key}/rating")
def my_rating(status_key: str, response: Response, c: Customer = Depends(current_customer)) -> dict:
    _no_store(response)
    try:
        return extras.my_rating(status_key, c.account.id)
    except online.OnlineError as e:
        raise fail(e) from None


@router.post("/orders/{status_key}/rating", status_code=201)
def rate(status_key: str, body: RatingIn, c: Customer = Depends(current_customer)) -> dict:
    try:
        return extras.rate(status_key, c.account.id, body.rating, body.comment)
    except online.OnlineError as e:
        raise fail(e) from None
