"""What the super admin does: sign in, make food courts, put outlets in them (README, "9.12").

Everything here runs on a session that sees every shop, so each function takes only the
ids it needs and checks the rest by hand. A super admin is not a shop user: nothing here
can be reached with a shop token, and no shop route accepts a platform token.
"""

import re
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_platform_token, hash_password, verify_password
from app.models import FoodCourt, FoodCourtOutlet, PlatformAdmin, Role, Shop, User
from app.schemas import _normalise_phone
from app.services import auth as auth_service
from app.services.online import OnlineError
from app.services.sample import seed_catalogue
from app.services.shops import ShopError, create_shop


# ---------------------------------------------------------------- the admin themselves
def make_admin(db: Session, name: str, phone: str, password: str | None = None) -> PlatformAdmin:
    """Used by scripts/new_platform_admin.py: there is no screen that makes a super admin."""
    phone = _normalise_phone(phone)
    if db.scalar(select(PlatformAdmin.id).where(PlatformAdmin.phone == phone)) is not None:
        raise ValueError(f"The number {phone} is already a super admin")
    admin = PlatformAdmin(
        name=name.strip() or "Super admin",
        phone=phone,
        password_hash=hash_password(password or secrets.token_urlsafe(24)),
    )
    db.add(admin)
    db.commit()
    return admin


def login(db: Session, phone: str, password: str) -> tuple[str, PlatformAdmin]:
    """Same rules as a shop login: a wrong phone and a wrong password look alike and take
    the same time, and repeated wrong passwords lock the account for a while."""
    admin = db.scalar(select(PlatformAdmin).where(PlatformAdmin.phone == phone).with_for_update())
    now = datetime.now(UTC)
    if admin is not None and admin.locked_until is not None and admin.locked_until > now:
        minutes = max(1, -(-int((admin.locked_until - now).total_seconds()) // 60))
        db.rollback()
        raise auth_service.LockedOut(
            f"Too many wrong passwords. Try again in {minutes} minute{'' if minutes == 1 else 's'}."
        )
    ok = verify_password(password, admin.password_hash if admin else None)
    if get_settings().dev_login and admin is not None:
        ok = True  # local testing only: config refuses this setting against a remote database
    if admin is not None and not ok:
        admin.failed_logins += 1
        if admin.failed_logins >= auth_service.MAX_FAILED_LOGINS:
            admin.failed_logins, admin.locked_until = 0, now + auth_service.LOCKOUT
        db.commit()
    if not ok or admin is None or not admin.is_active:
        db.rollback()
        raise auth_service.AuthError("Invalid phone or password")
    admin.failed_logins, admin.locked_until = 0, None
    db.commit()
    return create_platform_token(admin.id), admin


# ---------------------------------------------------------------- food courts
def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "court"
    return f"{base}-{secrets.token_hex(2)}"


def _court(db: Session, court_id: uuid.UUID) -> FoodCourt:
    court = db.get(FoodCourt, court_id)
    if court is None:
        raise OnlineError("not_found", "No such food court", 404)
    return court


def _outlet(db: Session, court: FoodCourt, outlet_id: uuid.UUID) -> FoodCourtOutlet:
    outlet = db.get(FoodCourtOutlet, outlet_id)
    if outlet is None or outlet.court_id != court.id:
        raise OnlineError("not_found", "No such outlet", 404)
    return outlet


def list_courts(db: Session) -> list[dict]:
    out = []
    for court in db.scalars(select(FoodCourt).order_by(FoodCourt.created_at)):
        rows = db.execute(
            select(FoodCourtOutlet, Shop)
            .join(Shop, Shop.id == FoodCourtOutlet.shop_id)
            .where(FoodCourtOutlet.court_id == court.id)
            .order_by(FoodCourtOutlet.joined_at)
        ).all()
        outlets = []
        for o, shop in rows:
            owner = db.scalar(
                select(User)
                .where(User.shop_id == shop.id, User.role == Role.owner)
                .order_by(User.created_at)
            )
            outlets.append(
                {
                    "id": o.id,
                    "name": shop.name,
                    "owner_name": owner.name if owner else "",
                    "owner_phone": owner.phone if owner else "",
                    "accepting_orders": o.accepting_orders,
                }
            )
        out.append({"id": court.id, "name": court.name, "slug": court.slug, "outlets": outlets})
    return out


def create_court(db: Session, admin_id: uuid.UUID, name: str) -> FoodCourt:
    court = FoodCourt(name=name.strip(), slug=_slug(name), created_by=admin_id)
    db.add(court)
    db.commit()
    return court


def add_new_outlet(
    db: Session,
    court_id: uuid.UUID,
    shop_name: str,
    owner_name: str,
    owner_phone: str,
    password: str | None,
    sample_menu: bool,
) -> FoodCourtOutlet:
    court = _court(db, court_id)
    if password:
        problem = auth_service.password_problem(password, _normalise_phone(owner_phone))
        if problem:
            raise OnlineError("weak_password", problem, 422)
    try:
        shop, owner = create_shop(shop_name, owner_phone, owner_name, password)
    except ShopError as e:
        raise OnlineError("cannot_create", str(e), 409) from None
    if sample_menu:
        seed_catalogue(shop, owner)
    outlet = FoodCourtOutlet(court_id=court.id, shop_id=shop.id)
    db.add(outlet)
    db.commit()
    return outlet


def attach_outlet(db: Session, court_id: uuid.UUID, owner_phone: str) -> FoodCourtOutlet:
    """Put a shop that already exists into the court, found by its owner's mobile number."""
    court = _court(db, court_id)
    try:
        phone = _normalise_phone(owner_phone)
    except ValueError as e:
        raise OnlineError("bad_phone", str(e), 422) from None
    owner = db.scalar(select(User).where(User.phone == phone, User.role == Role.owner))
    if owner is None:
        raise OnlineError("no_such_owner", "No shop owner has that number", 404)
    if db.scalar(select(FoodCourtOutlet.id).where(FoodCourtOutlet.shop_id == owner.shop_id)):
        raise OnlineError("already_in_a_court", "That shop is already in a food court", 409)
    outlet = FoodCourtOutlet(court_id=court.id, shop_id=owner.shop_id)
    db.add(outlet)
    db.commit()
    return outlet


def set_outlet_accepting(db: Session, court_id: uuid.UUID, outlet_id: uuid.UUID, on: bool) -> None:
    outlet = _outlet(db, _court(db, court_id), outlet_id)
    outlet.accepting_orders = on
    db.commit()


def remove_outlet(db: Session, court_id: uuid.UUID, outlet_id: uuid.UUID) -> None:
    """The shop and its orders are untouched: it just stops being in the court."""
    outlet = _outlet(db, _court(db, court_id), outlet_id)
    db.delete(outlet)
    db.commit()
