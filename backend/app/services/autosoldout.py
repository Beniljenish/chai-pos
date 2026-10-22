"""Dishes the shop cannot make any more, worked out from its stock (README, "9.17").

Only when the owner turns it on, and only from numbers the owner can trust: a raw ingredient
counts when it was once physically counted and what is left is less than one dish needs.
Made-in-shop ingredients (the tea decoction) are left out: the shop makes more when it runs
out, so zero on the shelf is not "sold out".
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IngredientKind, MenuItem
from app.services import recipes, stock


def short_items(db: Session) -> set[uuid.UUID]:
    on_hand = {
        h.ingredient.id: h.qty
        for h in stock.stock_on_hand(db)
        if h.has_opening and h.ingredient.kind == IngredientKind.raw
    }
    out: set[uuid.UUID] = set()
    for item_id in db.scalars(select(MenuItem.id).where(MenuItem.is_active)):
        recipe = recipes.resolve_recipe(db, menu_item_id=item_id)
        if recipe is None:
            continue
        if any(
            ln.ingredient_id in on_hand and on_hand[ln.ingredient_id] < ln.qty
            for ln in recipe.lines
        ):
            out.add(item_id)
    return out
