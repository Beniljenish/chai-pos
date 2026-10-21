"""Making a shop and its owner's login.

There is no sign-up screen: a shop exists because the super admin (or someone with
access to the database, through scripts/new_shop.py) made it here.
"""

import re
import secrets

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import Device, GstType, Role, Shop, User
from app.schemas import _normalise_phone


class ShopError(ValueError):
    pass


def create_shop(
    name: str, owner_phone: str, owner_name: str = "Owner", password: str | None = None
) -> tuple[Shop, User]:
    """A shop with one owner and one till (C1). With a password, the owner must
    choose their own at first login; without one, nobody knows a password (the
    owner is given one by a reset, or logs in through local test mode)."""
    try:
        phone = _normalise_phone(owner_phone)
    except ValueError as e:
        raise ShopError(str(e)) from None
    initials = "".join(w[0] for w in re.findall(r"[A-Za-z]+", name))[:2].upper() or "SH"
    db = mark_system(SessionLocal())
    try:
        if db.scalar(select(User.id).where(User.phone == phone)) is not None:
            raise ShopError(f"The number {phone} already has a login")
        shop = Shop(
            name=name.strip(),
            gst_type=GstType.unregistered,
            state_code="33",
            address="",
            invoice_prefix=initials,
        )
        db.add(shop)
        db.flush()
        owner = User(
            shop_id=shop.id,
            name=owner_name.strip() or "Owner",
            phone=phone,
            role=Role.owner,
            password_hash=hash_password(password or secrets.token_urlsafe(24)),
            # The person who typed the password knows it: the owner picks their own at first login.
            must_change_password=bool(password),
        )
        db.add_all([owner, Device(shop_id=shop.id, name="Counter 1", code="C1")])
        db.commit()
        db.refresh(shop)
        db.refresh(owner)
        return shop, owner
    finally:
        db.close()
