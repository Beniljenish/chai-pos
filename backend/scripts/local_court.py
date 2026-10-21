"""A food court to order from in a LOCAL database: "Demo Food Court", with the demo shop
(owner 9000000000) as its open outlet. Does nothing if any food court exists.

    python -m scripts.local_court

Customers then sign up at http://localhost:5173/order and find it in the list.
"""

import os

from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import FoodCourt, PlatformAdmin
from app.services import platform


def main() -> None:
    with mark_system(SessionLocal()) as db:
        if db.scalar(select(FoodCourt.id)) is not None:
            print("A food court already exists: nothing to do.")
            return
        admin = db.scalar(select(PlatformAdmin))
        if admin is None:
            raise SystemExit("Make the super admin first (scripts.new_platform_admin).")
        court = platform.create_court(db, admin.id, "Demo Food Court", "Demo Street, Chennai")
        outlet = platform.attach_outlet(
            db, court.id, os.environ.get("LOCAL_COURT_OWNER", "9000000000")
        )
        platform.set_outlet_accepting(db, court.id, outlet.id, True)
        print(f"Made {court.name}; its outlet is open. Customers: /order")


if __name__ == "__main__":
    main()
