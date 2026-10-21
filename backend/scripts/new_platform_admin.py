"""Make a super admin: someone who creates food courts and adds outlets to them.
There is no screen for this on purpose, so nobody can become one by clicking around.

    NEW_ADMIN_PHONE=9840000000 NEW_ADMIN_PASSWORD='something long' \
        python -m scripts.new_platform_admin

Optional:  NEW_ADMIN_NAME (default "Super admin").
Without NEW_ADMIN_PASSWORD a random one nobody sees is set: fine for local test mode,
which signs in by phone number alone. On a real database always give a password.
Running it again for the same number does nothing.
"""

import os
import sys

from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import PlatformAdmin
from app.schemas import _normalise_phone
from app.services import platform


def main() -> None:
    raw = os.environ.get("NEW_ADMIN_PHONE", "")
    if not raw:
        sys.exit("Set NEW_ADMIN_PHONE (and NEW_ADMIN_PASSWORD, 8+ characters, on a real database)")
    password = os.environ.get("NEW_ADMIN_PASSWORD") or None
    if password is not None and len(password) < 8:
        sys.exit("NEW_ADMIN_PASSWORD must be 8 characters or more")
    try:
        phone = _normalise_phone(raw)
    except ValueError as e:
        sys.exit(str(e))
    with mark_system(SessionLocal()) as db:
        if db.scalar(select(PlatformAdmin.id).where(PlatformAdmin.phone == phone)) is not None:
            print(f"{phone} is already a super admin: nothing to do.")
            return
        admin = platform.make_admin(
            db, os.environ.get("NEW_ADMIN_NAME", "Super admin"), phone, password
        )
    print(f"Created super admin {admin.name} ({phone}).")


if __name__ == "__main__":
    main()
