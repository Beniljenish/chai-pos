"""The placeholder catalogue: ingredients, a decoction, two drinks and two options.

Lives in the app (not in scripts/) because the super admin's "add an outlet with a sample
menu" uses it, and the deployed app does not include the scripts folder. scripts/seed.py
uses it too. Every number here is a typical guess, not data from a real shop.
"""

from decimal import Decimal as D

from app.db.session import SessionLocal
from app.db.tenancy import bind_tenant
from app.models import (
    BaseUnit,
    Ingredient,
    IngredientKind,
    MenuItem,
    MenuItemModifier,
    Modifier,
    ModifierLine,
    PackUnit,
    Shop,
    User,
)
from app.services import recipes


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
