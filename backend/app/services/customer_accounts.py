"""Customer accounts for ordering at food courts (README, "9.13").

Mobile number + password. No SMS, so no OTP: the number is a login name, not a verified
fact, and the kitchen is told so nowhere it could be misread as proof. Every rule here
mirrors the staff and super-admin logins (lockout, equal-time wrong-phone check), so the
three stay alike.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_customer_token, hash_password, verify_password
from app.models import (
    CustomerAccount,
    FoodCourt,
    FoodCourtOutlet,
    OnlineOrder,
    Order,
    OrderFeedback,
    Shop,
)
from app.services import auth as auth_service
from app.services import online, phone_codes, ratelimit
from app.services.online import OnlineError

# No 0/O/1/l/I: the admin reads this out over the phone.
_TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def _clean_name(name: str) -> str:
    return online._clean_text(name, 40)


def _issue(c: CustomerAccount) -> dict:
    return {
        "access_token": create_customer_token(c.id, c.token_version),
        "account": account_view(c),
    }


def account_view(c: CustomerAccount) -> dict:
    return {"name": c.name, "phone": c.phone, "must_change_password": c.must_change_password}


SIGNUPS_PER_HOUR = 8  # from one address: a family on one wifi, not a script


def signup(db: Session, name: str, phone: str, password: str, code: str = "", ip: str = "") -> dict:
    name = _clean_name(name)
    if not name:
        raise OnlineError("name_required", "Enter your name")
    problem = auth_service.password_problem(password, phone)
    if problem:
        raise OnlineError("weak_password", problem)
    if db.scalar(select(CustomerAccount.id).where(CustomerAccount.phone == phone)):
        raise OnlineError("phone_taken", "This number already has an account. Log in instead.", 409)
    try:
        ratelimit.hit(
            db,
            f"signup:{ip or 'unknown'}",
            limit=SIGNUPS_PER_HOUR,
            window=timedelta(hours=1),
            message="Too many accounts were made from here. Please try again in an hour.",
        )
    except ratelimit.RateLimited as e:
        db.rollback()
        raise OnlineError("too_many_signups", e.message, 429) from None
    verified = None
    if phone_codes.available():
        if not code.strip():
            db.rollback()
            raise OnlineError("code_required", "Enter the code sent to your mobile number.", 422)
        phone_codes.check(db, phone, "signup", code)
        verified = datetime.now(UTC)
    c = CustomerAccount(
        name=name, phone=phone, password_hash=hash_password(password), phone_verified_at=verified
    )
    db.add(c)
    try:
        db.commit()
    except IntegrityError:  # two sign-ups with one number at the same moment
        db.rollback()
        raise OnlineError(
            "phone_taken", "This number already has an account. Log in instead.", 409
        ) from None
    return _issue(c)


def login(db: Session, phone: str, password: str) -> dict:
    c = db.scalar(select(CustomerAccount).where(CustomerAccount.phone == phone).with_for_update())
    now = datetime.now(UTC)
    if c is not None and c.locked_until is not None and c.locked_until > now:
        minutes = max(1, -(-int((c.locked_until - now).total_seconds()) // 60))
        db.rollback()
        raise auth_service.LockedOut(
            f"Too many wrong passwords. Try again in {minutes} minute{'' if minutes == 1 else 's'}."
        )
    ok = verify_password(password, c.password_hash if c else None)
    if get_settings().dev_login and c is not None:
        ok = True  # local testing only: config refuses this setting against a remote database
    if c is not None and not ok:
        c.failed_logins += 1
        if c.failed_logins >= auth_service.MAX_FAILED_LOGINS:
            c.failed_logins, c.locked_until = 0, now + auth_service.LOCKOUT
        db.commit()
    if not ok or c is None or not c.is_active:
        db.rollback()
        raise auth_service.AuthError("Invalid phone or password")
    c.failed_logins, c.locked_until = 0, None
    db.commit()
    return _issue(c)


def change_password(db: Session, c: CustomerAccount, current: str, new: str) -> dict:
    if not verify_password(current, c.password_hash):
        raise OnlineError("wrong_password", "Your current password is not right", 403)
    problem = auth_service.password_problem(new, c.phone)
    if problem:
        raise OnlineError("weak_password", problem)
    if new == current:
        raise OnlineError("weak_password", "Choose a different password")
    c.password_hash = hash_password(new)
    c.must_change_password = False
    c.token_version += 1  # every other device is logged out
    db.commit()
    return _issue(c)


def reset_with_code(db: Session, phone: str, code: str, new: str) -> dict:
    """A forgotten password, reset by the customer: the code sent to their number is the proof."""
    c = db.scalar(select(CustomerAccount).where(CustomerAccount.phone == phone).with_for_update())
    if c is None or not c.is_active:
        # Same answer as a wrong code, so this cannot be used to find out who has an account.
        db.rollback()
        raise OnlineError("code_wrong", "That code is not right.", 422)
    phone_codes.check(db, phone, "reset", code)
    problem = auth_service.password_problem(new, phone)
    if problem:
        db.rollback()
        raise OnlineError("weak_password", problem)
    c.password_hash = hash_password(new)
    c.must_change_password = False
    c.token_version += 1
    c.failed_logins, c.locked_until = 0, None
    c.phone_verified_at = c.phone_verified_at or datetime.now(UTC)
    db.commit()
    return _issue(c)


def forgot(db: Session, phone: str) -> dict:
    """Send a reset code if the number has an account. The answer is the same either way."""
    if db.scalar(select(CustomerAccount.id).where(CustomerAccount.phone == phone)):
        return phone_codes.send(db, phone, "reset")
    return {"sent": True, "cooldown_seconds": int(phone_codes.COOLDOWN.total_seconds())}


def rename(db: Session, c: CustomerAccount, name: str) -> dict:
    name = _clean_name(name)
    if not name:
        raise OnlineError("name_required", "Enter your name")
    c.name = name
    db.commit()
    return account_view(c)


def admin_reset(db: Session, phone: str) -> dict:
    """A forgotten password, reset by the super admin: a temporary one the admin tells the
    customer, who must replace it at the next sign-in. Shown once, never stored in clear."""
    c = db.scalar(select(CustomerAccount).where(CustomerAccount.phone == phone).with_for_update())
    if c is None:
        raise OnlineError("not_found", "No customer account with that number", 404)
    temp = "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(8))
    c.password_hash = hash_password(temp)
    c.must_change_password = True
    c.token_version += 1
    c.failed_logins, c.locked_until = 0, None  # a locked-out customer is usually why they ask
    db.commit()
    return {"name": c.name, "phone": c.phone, "temporary_password": temp}


def history(db: Session, customer_id: uuid.UUID, limit: int = 50) -> list[dict]:
    """Their orders across every outlet, newest first. `db` is a system session: the
    orders live in different shops, and the only filter that matters is the customer."""
    rows = db.execute(
        select(OnlineOrder, Order, Shop, FoodCourt, FoodCourtOutlet, OrderFeedback.rating)
        .join(Order, Order.id == OnlineOrder.order_id)
        .join(Shop, Shop.id == OnlineOrder.shop_id)
        .join(FoodCourt, FoodCourt.id == OnlineOrder.court_id)
        .join(FoodCourtOutlet, FoodCourtOutlet.shop_id == OnlineOrder.shop_id)
        .outerjoin(OrderFeedback, OrderFeedback.online_order_id == OnlineOrder.id)
        .where(OnlineOrder.customer_id == customer_id)
        .order_by(Order.opened_at.desc())
        .limit(limit)
    ).all()
    out = []
    for oo, order, shop, court, outlet, rating in rows:
        lines = [ln for ln in order.state["lines"] if ln["qty"] > 0]
        out.append(
            {
                "token": oo.token,
                "outlet": shop.name,
                "outlet_id": outlet.id,  # which outlet tab "order again" goes to
                "court": court.name,
                "court_slug": court.slug,
                "placed_at": order.opened_at.isoformat(),
                "status": online.public_state(order.state),
                "items": [{"name": online.line_label(ln), "qty": ln["qty"]} for ln in lines],
                # what "order again" puts back in the cart: dish ids and option ids only; prices
                # and availability are looked up fresh
                "lines": [
                    {
                        "menu_item_id": ln["menu_item_id"],
                        "qty": ln["qty"],
                        "modifier_ids": [m["modifier_id"] for m in ln.get("modifiers") or []],
                    }
                    for ln in lines
                ],
                "total_paise": online._total(order.state["lines"], shop.gst_type),
                "status_key": online.status_key(oo.shop_id, order.id),
                "paid_online": oo.payment_id is not None,
                "rating": rating,
            }
        )
    return out
