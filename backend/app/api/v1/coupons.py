"""An outlet's offers, for its owner (README, "9.19"). The customer side is in customer_accounts."""

import re
import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from app.api.common import commit_or_409, get_or_404
from app.api.deps import Caller, require_owner
from app.models import Coupon
from app.services import coupons

router = APIRouter(tags=["offers"])


class CouponIn(BaseModel):
    code: str = Field(min_length=3, max_length=20)
    kind: str = Field(pattern="^(percent|amount)$")
    # a percentage (1 to 100), or paise (a whole number of rupees)
    value: int = Field(gt=0, le=1_000_000)
    min_order_paise: int = Field(default=0, ge=0, le=10_000_000)
    max_discount_paise: int | None = Field(default=None, gt=0, le=10_000_000)
    valid_until: date | None = None
    max_uses: int | None = Field(default=None, gt=0, le=1_000_000)

    @field_validator("code")
    @classmethod
    def clean(cls, v: str) -> str:
        v = re.sub(r"\s+", "", v).upper()
        if not re.fullmatch(r"[A-Z0-9]{3,20}", v):
            raise ValueError("Use 3 to 20 letters and numbers, no spaces")
        return v


class CouponPatch(BaseModel):
    is_active: bool | None = None
    valid_until: date | None = None
    max_uses: int | None = Field(default=None, gt=0, le=1_000_000)


@router.get("/coupons")
def list_coupons(caller: Caller = Depends(require_owner)) -> dict:
    return {"coupons": coupons.listing(caller.db)}


@router.post("/coupons", status_code=201)
def create_coupon(body: CouponIn, caller: Caller = Depends(require_owner)) -> dict:
    from app.api.common import unprocessable

    if body.kind == "percent":
        if body.value > 100:
            raise unprocessable("A percentage is from 1 to 100")
    else:
        if body.value % 100:
            raise unprocessable("An amount off is in whole rupees")
        if body.max_discount_paise is not None:
            raise unprocessable("A cap is only for a percentage")
    caller.db.add(
        Coupon(
            code=body.code,
            kind=body.kind,
            value=body.value,
            min_order_paise=body.min_order_paise,
            max_discount_paise=body.max_discount_paise,
            valid_until=body.valid_until,
            max_uses=body.max_uses,
        )
    )
    commit_or_409(caller.db, "You already have a code with that name")
    return {"coupons": coupons.listing(caller.db)}


@router.patch("/coupons/{coupon_id}")
def change_coupon(
    coupon_id: uuid.UUID, body: CouponPatch, caller: Caller = Depends(require_owner)
) -> dict:
    """Switch an offer off or on, move its last day, or change how many times it may be used.
    What it takes off is not editable: orders already placed used it. Make a new code instead."""
    c = get_or_404(caller.db, Coupon, coupon_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(c, field, value)
    caller.db.commit()
    return {"coupons": coupons.listing(caller.db)}
