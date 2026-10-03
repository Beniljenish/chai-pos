import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.gstin import GstinError, normalise_gstin
from app.models import GstType, Role

_PHONE = re.compile(r"^[6-9]\d{9}$")  # Indian mobile, 10 digits
# Deliberately simple: the test-email button is the real check.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$")


def _normalise_phone(v: str) -> str:
    digits = re.sub(r"\D", "", v)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if not _PHONE.match(digits):
        raise ValueError("Enter a 10-digit Indian mobile number")
    return digits


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth ---
class LoginIn(BaseModel):
    phone: str
    password: str = Field(min_length=1, max_length=128)

    _phone = field_validator("phone")(_normalise_phone)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)  # rules: auth.password_problem


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 (a scheme name, not a secret)
    expires_in: int


# --- shop ---
class ShopOut(ORM):
    id: uuid.UUID
    name: str
    gst_type: GstType
    gstin: str | None
    state_code: str
    address: str
    invoice_prefix: str
    report_email: str | None
    email_each_bill: bool
    email_day_end: bool
    email_daily: bool
    email_weekly: bool
    cash_shifts: bool


class ShopUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    gst_type: GstType | None = None
    gstin: str | None = None
    address: str | None = Field(default=None, max_length=500)
    report_email: str | None = Field(default=None, max_length=254)
    email_each_bill: bool | None = None
    email_day_end: bool | None = None
    email_daily: bool | None = None
    email_weekly: bool | None = None
    cash_shifts: bool | None = None

    @field_validator("report_email")
    @classmethod
    def valid_email(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if not v:
            return None  # cleared: no emails
        if not _EMAIL.match(v):
            raise ValueError("That does not look like an email address")
        return v

    @field_validator("gstin")
    @classmethod
    def valid_gstin(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            return normalise_gstin(v)
        except GstinError as e:
            raise ValueError(str(e)) from None


# --- users ---
class UserOut(ORM):
    id: uuid.UUID
    name: str
    phone: str
    role: Role
    is_active: bool
    must_change_password: bool
    locked: bool = False
    created_at: datetime


class UserCreate(BaseModel):
    """The owner sets a first password; the person must change it at first login."""

    name: str = Field(min_length=1, max_length=120)
    phone: str
    role: Role = Role.cashier
    password: str = Field(min_length=8, max_length=128)

    _phone = field_validator("phone")(_normalise_phone)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


# --- devices ---
class DeviceOut(ORM):
    id: uuid.UUID
    name: str
    code: str
    is_active: bool
    last_seen_at: datetime | None


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    is_active: bool | None = None
