"""An outlet's offers (README, "9.19"): a code that takes a percentage or a fixed amount off an
online order.

**The server decides everything.** The page only sends a code; the amount off, whether the code
still works and what the customer pays are worked out here, by the same rule the till uses when
it bills the order, so the bill equals what the customer owes to the paisa:

* the discount is a whole number of rupees (a percentage is rounded half up to the rupee, then
  capped), and it is the bill-level discount the till gives the order (`gst.compute_bill`), so the
  paid amount is `compute_bill(lines, discount).total` on both sides;
* at least one rupee is always payable (a 100% code would need a payment of nothing, which the
  payment service refuses);
* the outlet pays for its own offer. The food court's fee and the statements use what the
  customer actually paid.

A customer uses a code once, and a code has an optional total number of uses. A cancelled order
gives its use back. An order that was already paid for keeps its discount even if the code ran
out or was switched off while the customer paid.
"""

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import business_date, utcnow
from app.models import Coupon, CouponRedemption, Order, OrderStatus
from app.services.online import OnlineError

MIN_PAYABLE_PAISE = 100
_CODE = re.compile(r"^[A-Z0-9]{3,20}$")


def clean_code(raw: str) -> str:
    code = re.sub(r"\s+", "", raw or "").upper()
    if not _CODE.match(code):
        raise OnlineError("coupon_unknown", "That code is not valid", 422)
    return code


def discount_for(c: Coupon, total_paise: int) -> int:
    """Paise off a total of `total_paise` (whole rupees; never more than leaves ₹1 to pay)."""
    if c.kind == "percent":
        rupees = (total_paise * c.value * 2 + 10_000) // 20_000  # half up
        d = rupees * 100
        if c.max_discount_paise is not None:
            d = min(d, c.max_discount_paise // 100 * 100)
    else:
        d = c.value // 100 * 100
    return max(0, min(d, (total_paise - MIN_PAYABLE_PAISE) // 100 * 100))


def _uses(db: Session, coupon_id: uuid.UUID, customer_id: uuid.UUID | None = None) -> int:
    q = (
        select(func.count())
        .select_from(CouponRedemption)
        .join(Order, Order.id == CouponRedemption.order_id)
        .where(CouponRedemption.coupon_id == coupon_id, Order.status != OrderStatus.cancelled)
    )
    if customer_id is not None:
        q = q.where(CouponRedemption.customer_id == customer_id)
    return db.scalar(q) or 0


def resolve(
    db: Session,
    code: str,
    customer_id: uuid.UUID | None,
    total_paise: int,
    *,
    strict: bool = True,
    lock: bool = False,
) -> tuple[Coupon, int]:
    """The coupon and the paise it takes off `total_paise`, or why not. `db` is the outlet's own
    session (coupons belong to one shop). `strict=False` is for an order already paid for."""
    code = clean_code(code)
    q = select(Coupon).where(Coupon.code == code)
    coupon = db.scalar(q.with_for_update() if lock else q)
    if coupon is None:
        raise OnlineError("coupon_unknown", "That code is not valid", 422)
    if strict:
        if not coupon.is_active:
            raise OnlineError("coupon_off", "This offer has ended", 422)
        if coupon.valid_until is not None and coupon.valid_until < business_date(utcnow()):
            raise OnlineError("coupon_expired", "This offer has expired", 422)
        if total_paise < coupon.min_order_paise:
            raise OnlineError(
                "coupon_min",
                f"Spend ₹{coupon.min_order_paise // 100} or more to use this code",
                422,
                {"min_order_paise": coupon.min_order_paise},
            )
        if coupon.max_uses is not None and _uses(db, coupon.id) >= coupon.max_uses:
            raise OnlineError("coupon_used_up", "This offer has been used up", 422)
        if customer_id is not None and _uses(db, coupon.id, customer_id) > 0:
            raise OnlineError("coupon_already_used", "You have already used this code", 422)
    d = discount_for(coupon, total_paise)
    if d <= 0:
        raise OnlineError("coupon_min", "This code does not take anything off this order", 422)
    return coupon, d


def redeem(
    db: Session, coupon: Coupon, order_id: uuid.UUID, customer_id: uuid.UUID | None, discount: int
) -> None:
    db.add(
        CouponRedemption(
            coupon_id=coupon.id, order_id=order_id, customer_id=customer_id, discount_paise=discount
        )
    )


def listing(db: Session) -> list[dict]:
    rows = db.scalars(select(Coupon).order_by(Coupon.created_at.desc())).all()
    return [
        {
            "id": c.id,
            "code": c.code,
            "kind": c.kind,
            "value": c.value,
            "min_order_paise": c.min_order_paise,
            "max_discount_paise": c.max_discount_paise,
            "valid_until": c.valid_until,
            "max_uses": c.max_uses,
            "is_active": c.is_active,
            "uses": _uses(db, c.id),
        }
        for c in rows
    ]
