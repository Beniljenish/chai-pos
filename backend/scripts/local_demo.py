"""Four weeks of demo data in a LOCAL database, with logins you can use.

scripts.demo_data is built for the staging load (it reuses staging's ids and
gives every login a random password). This wraps it for a laptop: fresh ids,
one owner (demo_data adds the cashiers), and the password you choose on every
login.

    DEMO_PASSWORD=... python -m scripts.local_demo

Logins: owner 9000000000; cashiers 9000020001 (Ravi), 9000020002 (Priya), 9000020003.
It refuses to run on a database that already has a shop.
"""

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import User
from scripts import demo_data


def main() -> None:
    password = os.environ.get("DEMO_PASSWORD", "")
    if len(password) < 8:
        sys.exit("Set DEMO_PASSWORD (8 characters or more): it becomes every demo login's password")
    keep = {
        "shop_id": str(uuid.uuid4()),
        "users": [
            {"id": str(uuid.uuid4()), "name": "Owner", "role": "owner"},
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "keep.json"
        path.write_text(json.dumps(keep))
        os.environ["DEMO_KEEP"] = str(path)
        demo_data.main()

    db = mark_system(SessionLocal())
    try:
        users = db.scalars(select(User).order_by(User.phone)).all()
        for u in users:
            u.password_hash = hash_password(password)
            u.must_change_password = False
        db.commit()
        for u in users:
            print(f"  {u.phone}  {u.name} ({u.role})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
