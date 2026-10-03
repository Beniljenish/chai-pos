"""Create placeholder data for local development.

PLACEHOLDER: every quantity, price and pack size below is a typical guess for a
Chennai tea stall. Replace them with real numbers after the pilot-shop visit.

Usage:  SEED_PASSWORD=... python -m scripts.seed
"""

import os
import sys
from decimal import Decimal as D

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.db.tenancy import bind_tenant, mark_system
from app.models import (
    BaseUnit,
    Device,
    GstType,
    Ingredient,
    IngredientKind,
    MenuItem,
    MenuItemModifier,
    Modifier,
    ModifierLine,
    PackUnit,
    Role,
    Shop,
    User,
)
from app.services import recipes

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


def seed_catalogue(shop: Shop, owner: User) -> None:
    # Uses a normal tenant-bound session and the real services: the seed
    # exercises the same rules the API does.
    db = bind_tenant(SessionLocal(), shop.id)

    def ingredient(
        name, unit, kind=IngredientKind.raw, packs=(), tolerance_bp=300, scales_with_size=True
    ):
        i = Ingredient(
            name=name,
            base_unit=unit,
            kind=kind,
            tolerance_bp=tolerance_bp,
            scales_with_size=scales_with_size,
        )
        i.pack_units = [PackUnit(name=n, qty_in_base=D(q)) for n, q in packs]
        db.add(i)
        db.flush()
        return i

    milk = ingredient(
        "Milk", BaseUnit.ml, packs=[("packet", 500), ("crate", 12000)], tolerance_bp=800
    )
    tea_powder = ingredient("Tea powder", BaseUnit.g, packs=[("pouch", 250), ("kg bag", 1000)])
    sugar = ingredient("Sugar", BaseUnit.g, packs=[("bag", 1000)])
    oranges = ingredient("Oranges", BaseUnit.g, tolerance_bp=800)
    cups = ingredient("Paper cup", BaseUnit.piece, packs=[("sleeve", 50)], scales_with_size=False)
    decoction = ingredient("Tea decoction", BaseUnit.ml, kind=IngredientKind.prep)

    L = recipes.LineIn
    recipes.set_prep_recipe(
        db,
        decoction,
        [L(milk.id, D(2000)), L(tea_powder.id, D(60)), L(sugar.id, D(150))],
        yield_qty=D(2200),
        user_id=owner.id,
    )
    tea = MenuItem(name="Masala tea", category="Tea", price_paise=2000)
    juice = MenuItem(name="Orange juice", category="Juice", price_paise=6000)
    db.add_all([tea, juice])
    db.flush()
    recipes.set_menu_item_recipe(
        db, tea, [L(decoction.id, D(100)), L(cups.id, D(1))], None, owner.id
    )
    recipes.set_menu_item_recipe(
        db,
        juice,
        [L(cups.id, D(1))],
        recipes.JuiceYieldIn(oranges.id, ml_per_kg=D(450), portion_ml=D(250)),
        owner.id,
    )
    less_sugar = Modifier(
        name="Less sugar", lines=[ModifierLine(ingredient_id=sugar.id, qty_delta=D(-5))]
    )
    large = Modifier(name="Large", price_delta_paise=1000, scale_factor=D("1.5"))
    db.add_all([less_sugar, large])
    db.flush()
    db.add_all(
        [
            MenuItemModifier(menu_item_id=tea.id, modifier_id=less_sugar.id),
            MenuItemModifier(menu_item_id=tea.id, modifier_id=large.id),
            MenuItemModifier(menu_item_id=juice.id, modifier_id=large.id),
        ]
    )
    db.commit()
    db.close()


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
