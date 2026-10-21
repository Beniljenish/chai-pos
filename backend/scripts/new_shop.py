"""Add another shop (an outlet) with its owner's login, in whatever database
DATABASE_URL points at. There is no sign-up screen: a shop exists because someone
with access to the database made it, and this is how.

    NEW_SHOP_NAME="Anna Biryani" NEW_OWNER_PHONE=9841100000 python -m scripts.new_shop

Optional:
    NEW_OWNER_NAME      the owner's name (default "Owner")
    NEW_OWNER_PASSWORD  8+ characters; the owner must choose their own at first login.
                        Left out, a random one nobody sees is set (fine for local test
                        mode, which logs in by phone number alone).
    SAMPLE_MENU=1       also add the placeholder menu, ingredients and recipes
"""

import os
import re
import secrets
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import Device, GstType, Role, Shop, User
from app.schemas import _normalise_phone
from scripts import seed


def create_shop(
    name: str, owner_phone: str, owner_name: str = "Owner", password: str | None = None
) -> tuple[Shop, User]:
    phone = _normalise_phone(owner_phone)
    initials = "".join(w[0] for w in re.findall(r"[A-Za-z]+", name))[:2].upper() or "SH"
    db = mark_system(SessionLocal())
    try:
        if db.scalar(select(User.id).where(User.phone == phone)) is not None:
            raise ValueError(f"The number {phone} already has a login")
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


def main() -> None:
    name = os.environ.get("NEW_SHOP_NAME", "").strip()
    phone = os.environ.get("NEW_OWNER_PHONE", "")
    if len(name) < 2 or not phone:
        sys.exit(
            "Set NEW_SHOP_NAME and NEW_OWNER_PHONE, for example "
            'NEW_SHOP_NAME="Anna Biryani" NEW_OWNER_PHONE=9841100000'
        )
    password = os.environ.get("NEW_OWNER_PASSWORD") or None
    if password is not None and len(password) < 8:
        sys.exit("NEW_OWNER_PASSWORD must be 8 characters or more")
    try:
        shop, owner = create_shop(name, phone, os.environ.get("NEW_OWNER_NAME", "Owner"), password)
    except ValueError as e:
        sys.exit(str(e))
    if os.environ.get("SAMPLE_MENU") == "1":
        seed.seed_catalogue(shop, owner)
    print(
        f"Created {shop.name}: owner {owner.phone}"
        + (" (with the sample menu)" if os.environ.get("SAMPLE_MENU") == "1" else "")
    )


if __name__ == "__main__":
    main()
