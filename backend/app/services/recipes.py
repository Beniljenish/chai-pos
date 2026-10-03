"""Recipes are immutable versions. "Editing" a recipe inserts version N+1.

Phase 2 bills will store the recipe_id they were sold under, so changing the
SOP today can never change what last week's sales consumed.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.time import utcnow
from app.models import BaseUnit, Ingredient, IngredientKind, MenuItem, Recipe, RecipeLine

Q3 = Decimal("0.001")


class RecipeError(ValueError):
    pass


@dataclass(frozen=True)
class LineIn:
    ingredient_id: uuid.UUID
    qty: Decimal


@dataclass(frozen=True)
class JuiceYieldIn:
    """1 kg of fruit gives `ml_per_kg` ml of juice; one serving is `portion_ml`."""

    ingredient_id: uuid.UUID
    ml_per_kg: Decimal
    portion_ml: Decimal


def fruit_grams_per_portion(ml_per_kg: Decimal, portion_ml: Decimal) -> Decimal:
    # 250 ml / 450 ml-per-kg * 1000 g = 555.556 g
    return (portion_ml / ml_per_kg * 1000).quantize(Q3, rounding=ROUND_HALF_UP)


def _load_ingredients(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, Ingredient]:
    # Tenant-scoped: another shop's ingredient id simply isn't found.
    rows = db.scalars(select(Ingredient).where(Ingredient.id.in_(ids))).all()
    found = {i.id: i for i in rows}
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise RecipeError(f"Unknown ingredient(s): {', '.join(missing)}")
    inactive = [i.name for i in rows if not i.is_active]
    if inactive:
        raise RecipeError(f"Inactive ingredient(s): {', '.join(inactive)}")
    return found


def _next_version(db: Session, column, output_id: uuid.UUID) -> int:
    current = db.scalar(select(func.max(Recipe.version)).where(column == output_id))
    return (current or 0) + 1


def set_menu_item_recipe(
    db: Session,
    item: MenuItem,
    lines: list[LineIn],
    juice: JuiceYieldIn | None,
    user_id: uuid.UUID,
) -> Recipe:
    all_lines = list(lines)
    yield_inputs = None
    if juice is not None:
        fruit = _load_ingredients(db, [juice.ingredient_id])[juice.ingredient_id]
        if fruit.base_unit != BaseUnit.g:
            raise RecipeError("Juice yield needs a fruit measured in grams")
        grams = fruit_grams_per_portion(juice.ml_per_kg, juice.portion_ml)
        all_lines.append(LineIn(juice.ingredient_id, grams))
        yield_inputs = {
            "ingredient_id": str(juice.ingredient_id),
            "ml_per_kg": str(juice.ml_per_kg),
            "portion_ml": str(juice.portion_ml),
            "grams_per_portion": str(grams),
        }
    if not all_lines:
        raise RecipeError("A recipe needs at least one ingredient")
    _check_duplicates(all_lines)
    _load_ingredients(db, [ln.ingredient_id for ln in all_lines])  # menu items may use prep

    recipe = Recipe(
        menu_item_id=item.id,
        version=_next_version(db, Recipe.menu_item_id, item.id),
        effective_from=utcnow(),
        yield_inputs=yield_inputs,
        created_by=user_id,
    )
    return _save(db, recipe, all_lines)


def set_prep_recipe(
    db: Session,
    prep: Ingredient,
    lines: list[LineIn],
    yield_qty: Decimal,
    user_id: uuid.UUID,
) -> Recipe:
    if prep.kind != IngredientKind.prep:
        raise RecipeError("Only prep ingredients (e.g. decoction) have a batch recipe")
    if not lines:
        raise RecipeError("A recipe needs at least one ingredient")
    _check_duplicates(lines)
    found = _load_ingredients(db, [ln.ingredient_id for ln in lines])
    # v1 decision: a prep is made only from raw ingredients (no nesting, no cycles).
    nested = [i.name for i in found.values() if i.kind != IngredientKind.raw]
    if nested:
        raise RecipeError(f"Prep recipes can only use raw ingredients, not: {', '.join(nested)}")

    recipe = Recipe(
        prep_ingredient_id=prep.id,
        version=_next_version(db, Recipe.prep_ingredient_id, prep.id),
        effective_from=utcnow(),
        yield_qty=yield_qty.quantize(Q3),
        created_by=user_id,
    )
    return _save(db, recipe, lines)


def _check_duplicates(lines: list[LineIn]) -> None:
    ids = [ln.ingredient_id for ln in lines]
    if len(ids) != len(set(ids)):
        raise RecipeError("Each ingredient may appear only once in a recipe")


def _save(db: Session, recipe: Recipe, lines: list[LineIn]) -> Recipe:
    db.add(recipe)
    db.flush()
    for ln in lines:
        db.add(RecipeLine(recipe_id=recipe.id, ingredient_id=ln.ingredient_id, qty=ln.qty))
    db.flush()
    db.refresh(recipe, ["lines"])
    return recipe


def resolve_recipe(
    db: Session,
    *,
    menu_item_id: uuid.UUID | None = None,
    prep_ingredient_id: uuid.UUID | None = None,
    at: datetime | None = None,
) -> Recipe | None:
    """The version in force at `at` (default: now)."""
    column, output_id = (
        (Recipe.menu_item_id, menu_item_id)
        if menu_item_id is not None
        else (Recipe.prep_ingredient_id, prep_ingredient_id)
    )
    return db.scalar(
        select(Recipe)
        .where(column == output_id, Recipe.effective_from <= (at or utcnow()))
        .order_by(Recipe.version.desc())
        .limit(1)
        .options(selectinload(Recipe.lines).selectinload(RecipeLine.ingredient))
    )
