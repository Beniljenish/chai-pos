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
import sys

from app.services.sample import seed_catalogue
from app.services.shops import ShopError, create_shop


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
    except ShopError as e:
        sys.exit(str(e))
    if os.environ.get("SAMPLE_MENU") == "1":
        seed_catalogue(shop, owner)
    print(
        f"Created {shop.name}: owner {owner.phone}"
        + (" (with the sample menu)" if os.environ.get("SAMPLE_MENU") == "1" else "")
    )


if __name__ == "__main__":
    main()
