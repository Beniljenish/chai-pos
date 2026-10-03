"""Create placeholder data for local development.

PLACEHOLDER: replace the shop details after the pilot-shop visit.
Usage:  python -m scripts.seed
"""

import os
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import Device, GstType, Role, Shop, User

OWNER_PHONE = "9000000001"
CASHIER_PHONE = "9000000002"


def main() -> None:
    password = os.environ.get("SEED_PASSWORD")
    if not password or len(password) < 8:
        sys.exit("Set SEED_PASSWORD (8+ chars) for the seeded owner and cashier")

    db = mark_system(SessionLocal())
    if db.scalar(select(User).where(User.phone == OWNER_PHONE)):
        print("Seed data already present, nothing to do.")
        return

    shop = Shop(
        name="Demo Tea Stall (placeholder)",
        gst_type=GstType.unregistered,
        state_code="33",
        address="Chennai, Tamil Nadu",
        invoice_prefix="DT",
    )
    db.add(shop)
    db.flush()
    db.add_all(
        [
            User(
                shop_id=shop.id,
                name="Owner",
                phone=OWNER_PHONE,
                role=Role.owner,
                password_hash=hash_password(password),
            ),
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
    print(f"Seeded shop {shop.id}: owner {OWNER_PHONE}, cashier {CASHIER_PHONE}")


if __name__ == "__main__":
    main()
