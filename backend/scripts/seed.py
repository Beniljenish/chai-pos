"""Create placeholder data for local development.

PLACEHOLDER: every quantity, price and pack size below is a typical guess for a
Chennai tea stall. Replace them with real numbers after the pilot-shop visit.

Usage:  SEED_PASSWORD=... python -m scripts.seed
"""

import os
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import (
    Device,
    GstType,
    Role,
    Shop,
    User,
)
from app.services.sample import seed_catalogue

OWNER_PHONE = "9000000001"
CASHIER_PHONE = "9000000002"


def seed_shop(password: str) -> tuple[Shop, User]:
    db = mark_system(SessionLocal())
    shop = Shop(
        name="Demo Tea Stall (placeholder)",
        gst_type=GstType.unregistered,
        state_code="33",
        address="Chennai, Tamil Nadu",
        invoice_prefix="DT",
    )
    db.add(shop)
    db.flush()
    owner = User(
        shop_id=shop.id,
        name="Owner",
        phone=OWNER_PHONE,
        role=Role.owner,
        password_hash=hash_password(password),
    )
    db.add_all(
        [
            owner,
            User(
                shop_id=shop.id,
                name="Cashier",
                phone=CASHIER_PHONE,
                role=Role.cashier,
                password_hash=hash_password(password),
            ),
            Device(shop_id=shop.id, name="Counter 1", code="C1"),
        ]
    )
    db.commit()
    db.close()
    return shop, owner


def main() -> None:
    password = os.environ.get("SEED_PASSWORD")
    if not password or len(password) < 8:
        sys.exit("Set SEED_PASSWORD (8+ chars) for the seeded owner and cashier")

    check = mark_system(SessionLocal())
    exists = check.scalar(select(User).where(User.phone == OWNER_PHONE))
    check.close()
    if exists:
        print("Seed data already present, nothing to do.")
        return
    shop, owner = seed_shop(password)
    seed_catalogue(shop, owner)
    print(
        f"Seeded shop {shop.id}: owner {OWNER_PHONE}, cashier {CASHIER_PHONE}, "
        "6 ingredients, 2 menu items, 2 modifiers (all placeholders)"
    )


if __name__ == "__main__":
    main()
