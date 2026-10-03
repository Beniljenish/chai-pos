"""Menu, ingredients, recipes and modifiers (owner manages; cashiers read the catalogue)."""

import hashlib
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Response, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.api.common import commit_or_409, get_or_404, unprocessable
from app.api.deps import Caller, get_caller, require_owner
from app.models import (
    Ingredient,
    IngredientKind,
    MenuItem,
    MenuItemModifier,
    Modifier,
    ModifierLine,
    PackUnit,
    Recipe,
    Shop,
)
from app.schemas_catalogue import (
    IngredientCreate,
    IngredientOut,
    IngredientUpdate,
    MenuItemCreate,
    MenuItemOut,
    MenuItemUpdate,
    MenuRecipeIn,
    ModifierCreate,
    ModifierIdsIn,
    ModifierOut,
    ModifierUpdate,
    PackUnitIn,
    PackUnitOut,
    PrepRecipeIn,
    RecipeLineOut,
    RecipeOut,
)
from app.services import recipes as recipe_service

router = APIRouter()


def _ingredient(caller: Caller, ingredient_id: uuid.UUID) -> Ingredient:
    return get_or_404(caller.db, Ingredient, ingredient_id)


def _recipe_out(recipe: Recipe | None) -> RecipeOut | None:
    if recipe is None:
        return None
    return RecipeOut(
        id=recipe.id,
        version=recipe.version,
        effective_from=recipe.effective_from,
        yield_qty=recipe.yield_qty,
        yield_inputs=recipe.yield_inputs,
        lines=[
            RecipeLineOut(
                ingredient_id=ln.ingredient_id,
                ingredient_name=ln.ingredient.name,
                base_unit=ln.ingredient.base_unit,
                qty=ln.qty,
            )
            for ln in recipe.lines
        ],
    )


# ---------------- ingredients ----------------
@router.get("/ingredients", response_model=list[IngredientOut], tags=["ingredients"])
def list_ingredients(caller: Caller = Depends(get_caller)):
    return caller.db.scalars(
        select(Ingredient).options(selectinload(Ingredient.pack_units)).order_by(Ingredient.name)
    ).all()


@router.post("/ingredients", response_model=IngredientOut, status_code=201, tags=["ingredients"])
def create_ingredient(body: IngredientCreate, caller: Caller = Depends(require_owner)):
    data = body.model_dump(exclude={"pack_units"})
    ingredient = Ingredient(**data)
    # Built through the relationship so nothing hits the DB before commit_or_409:
    # a duplicate name must be a clean 409, never a 500.
    ingredient.pack_units = [PackUnit(**pu.model_dump()) for pu in body.pack_units]
    caller.db.add(ingredient)
    commit_or_409(caller.db, "An ingredient (or pack unit) with that name already exists")
    caller.db.refresh(ingredient, ["pack_units"])
    return ingredient


@router.get("/ingredients/{ingredient_id}", response_model=IngredientOut, tags=["ingredients"])
def get_ingredient(ingredient_id: uuid.UUID, caller: Caller = Depends(get_caller)):
    return _ingredient(caller, ingredient_id)


@router.patch("/ingredients/{ingredient_id}", response_model=IngredientOut, tags=["ingredients"])
def update_ingredient(
    ingredient_id: uuid.UUID, body: IngredientUpdate, caller: Caller = Depends(require_owner)
):
    ingredient = _ingredient(caller, ingredient_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(ingredient, field, value)
    commit_or_409(caller.db, "An ingredient with that name already exists")
    return ingredient


@router.get(
    "/ingredients/{ingredient_id}/pack-units",
    response_model=list[PackUnitOut],
    tags=["ingredients"],
)
def list_pack_units(ingredient_id: uuid.UUID, caller: Caller = Depends(get_caller)):
    return _ingredient(caller, ingredient_id).pack_units


@router.post(
    "/ingredients/{ingredient_id}/pack-units",
    response_model=PackUnitOut,
    status_code=201,
    tags=["ingredients"],
)
def add_pack_unit(
    ingredient_id: uuid.UUID, body: PackUnitIn, caller: Caller = Depends(require_owner)
):
    # Pack units are never edited: changing "1 crate" from 24 to 20 packets would
    # silently rewrite how past receipts were understood. Add a new unit instead.
    ingredient = _ingredient(caller, ingredient_id)
    unit = PackUnit(ingredient_id=ingredient.id, **body.model_dump())
    caller.db.add(unit)
    commit_or_409(caller.db, "That pack unit already exists for this ingredient")
    return unit


@router.get(
    "/ingredients/{ingredient_id}/recipe", response_model=RecipeOut | None, tags=["recipes"]
)
def get_prep_recipe(
    ingredient_id: uuid.UUID, at: datetime | None = None, caller: Caller = Depends(get_caller)
):
    ingredient = _ingredient(caller, ingredient_id)
    return _recipe_out(
        recipe_service.resolve_recipe(caller.db, prep_ingredient_id=ingredient.id, at=at)
    )


@router.put("/ingredients/{ingredient_id}/recipe", response_model=RecipeOut, tags=["recipes"])
def set_prep_recipe(
    ingredient_id: uuid.UUID, body: PrepRecipeIn, caller: Caller = Depends(require_owner)
):
    ingredient = _ingredient(caller, ingredient_id)  # 404 before any body validation
    try:
        recipe_service.set_prep_recipe(
            caller.db,
            ingredient,
            [recipe_service.LineIn(ln.ingredient_id, ln.qty) for ln in body.lines],
            body.yield_qty,
            caller.user.id,
        )
    except recipe_service.RecipeError as e:
        caller.db.rollback()
        raise unprocessable(str(e)) from None
    commit_or_409(caller.db, "Recipe changed at the same moment by someone else; retry")
    return _recipe_out(recipe_service.resolve_recipe(caller.db, prep_ingredient_id=ingredient.id))


# ---------------- menu items ----------------
@router.get("/menu-items", response_model=list[MenuItemOut], tags=["menu"])
def list_menu_items(caller: Caller = Depends(get_caller)):
    return caller.db.scalars(select(MenuItem).order_by(MenuItem.category, MenuItem.name)).all()


@router.post("/menu-items", response_model=MenuItemOut, status_code=201, tags=["menu"])
def create_menu_item(body: MenuItemCreate, caller: Caller = Depends(require_owner)):
    item = MenuItem(**body.model_dump())
    caller.db.add(item)
    commit_or_409(caller.db, "A menu item with that name already exists")
    return item


@router.get("/menu-items/{menu_item_id}", response_model=MenuItemOut, tags=["menu"])
def get_menu_item(menu_item_id: uuid.UUID, caller: Caller = Depends(get_caller)):
    return get_or_404(caller.db, MenuItem, menu_item_id)


@router.patch("/menu-items/{menu_item_id}", response_model=MenuItemOut, tags=["menu"])
def update_menu_item(
    menu_item_id: uuid.UUID, body: MenuItemUpdate, caller: Caller = Depends(require_owner)
):
    item = get_or_404(caller.db, MenuItem, menu_item_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    commit_or_409(caller.db, "A menu item with that name already exists")
    return item


@router.get("/menu-items/{menu_item_id}/recipe", response_model=RecipeOut | None, tags=["recipes"])
def get_menu_recipe(
    menu_item_id: uuid.UUID, at: datetime | None = None, caller: Caller = Depends(get_caller)
):
    item = get_or_404(caller.db, MenuItem, menu_item_id)
    return _recipe_out(recipe_service.resolve_recipe(caller.db, menu_item_id=item.id, at=at))


@router.put("/menu-items/{menu_item_id}/recipe", response_model=RecipeOut, tags=["recipes"])
def set_menu_recipe(
    menu_item_id: uuid.UUID, body: MenuRecipeIn, caller: Caller = Depends(require_owner)
):
    item = get_or_404(caller.db, MenuItem, menu_item_id)
    juice = (
        recipe_service.JuiceYieldIn(**body.juice_yield.model_dump()) if body.juice_yield else None
    )
    try:
        recipe_service.set_menu_item_recipe(
            caller.db,
            item,
            [recipe_service.LineIn(ln.ingredient_id, ln.qty) for ln in body.lines],
            juice,
            caller.user.id,
        )
    except recipe_service.RecipeError as e:
        caller.db.rollback()
        raise unprocessable(str(e)) from None
    commit_or_409(caller.db, "Recipe changed at the same moment by someone else; retry")
    return _recipe_out(recipe_service.resolve_recipe(caller.db, menu_item_id=item.id))


@router.put("/menu-items/{menu_item_id}/modifiers", response_model=list[ModifierOut], tags=["menu"])
def set_menu_item_modifiers(
    menu_item_id: uuid.UUID, body: ModifierIdsIn, caller: Caller = Depends(require_owner)
):
    item = get_or_404(caller.db, MenuItem, menu_item_id)
    ids = set(body.modifier_ids)
    mods = caller.db.scalars(
        select(Modifier).where(Modifier.id.in_(ids)).options(selectinload(Modifier.lines))
    ).all()
    if len(mods) != len(ids):
        raise unprocessable("Unknown modifier id")
    caller.db.execute(delete(MenuItemModifier).where(MenuItemModifier.menu_item_id == item.id))
    for m in mods:
        caller.db.add(MenuItemModifier(menu_item_id=item.id, modifier_id=m.id))
    caller.db.commit()
    return sorted(mods, key=lambda m: m.name)


# ---------------- modifiers ----------------
def _modifier(caller: Caller, modifier_id: uuid.UUID) -> Modifier:
    mod = caller.db.scalar(
        select(Modifier).where(Modifier.id == modifier_id).options(selectinload(Modifier.lines))
    )
    if mod is None:
        get_or_404(caller.db, Modifier, modifier_id)  # raises the standard 404
    return mod


def _check_line_ingredients(caller: Caller, lines) -> None:
    ids = [ln.ingredient_id for ln in lines]
    if len(ids) != len(set(ids)):
        raise unprocessable("Each ingredient may appear only once in a modifier")
    found = caller.db.scalars(select(Ingredient.id).where(Ingredient.id.in_(ids))).all()
    if len(found) != len(set(ids)):
        raise unprocessable("Unknown ingredient in modifier lines")


@router.get("/modifiers", response_model=list[ModifierOut], tags=["menu"])
def list_modifiers(caller: Caller = Depends(get_caller)):
    return caller.db.scalars(
        select(Modifier).options(selectinload(Modifier.lines)).order_by(Modifier.name)
    ).all()


@router.post("/modifiers", response_model=ModifierOut, status_code=201, tags=["menu"])
def create_modifier(body: ModifierCreate, caller: Caller = Depends(require_owner)):
    _check_line_ingredients(caller, body.lines)
    mod = Modifier(**body.model_dump(exclude={"lines"}))
    mod.lines = [ModifierLine(**ln.model_dump()) for ln in body.lines]
    caller.db.add(mod)
    commit_or_409(caller.db, "A modifier with that name already exists")
    return mod


@router.get("/modifiers/{modifier_id}", response_model=ModifierOut, tags=["menu"])
def get_modifier(modifier_id: uuid.UUID, caller: Caller = Depends(get_caller)):
    return _modifier(caller, modifier_id)


@router.patch("/modifiers/{modifier_id}", response_model=ModifierOut, tags=["menu"])
def update_modifier(
    modifier_id: uuid.UUID, body: ModifierUpdate, caller: Caller = Depends(require_owner)
):
    mod = _modifier(caller, modifier_id)
    data = body.model_dump(exclude_unset=True)
    if "lines" in data:
        _check_line_ingredients(caller, body.lines)
        # Safe to replace: Phase 2 bills snapshot the modifier's effect at sale time.
        mod.lines = [ModifierLine(**ln.model_dump()) for ln in body.lines]
        data.pop("lines")
    for field, value in data.items():
        setattr(mod, field, value)
    commit_or_409(caller.db, "A modifier with that name already exists")
    return mod


# ---------------- catalogue (what a billing device caches) ----------------
@router.get("/catalogue", tags=["menu"])
def catalogue(
    response: Response,
    if_none_match: str | None = Header(default=None),
    caller: Caller = Depends(get_caller),
):
    db = caller.db
    shop = db.scalar(select(Shop))
    items = db.scalars(select(MenuItem).where(MenuItem.is_active).order_by(MenuItem.name)).all()
    links = db.execute(select(MenuItemModifier.menu_item_id, MenuItemModifier.modifier_id)).all()
    mods = db.scalars(
        select(Modifier).where(Modifier.is_active).options(selectinload(Modifier.lines))
    ).all()
    ingredients = db.scalars(select(Ingredient).where(Ingredient.is_active)).all()

    payload = jsonable_encoder(
        {
            "shop": {
                "name": shop.name,
                "gst_type": shop.gst_type,
                "gstin": shop.gstin,
                "state_code": shop.state_code,
                "address": shop.address,
            },
            "menu_items": [
                {
                    **MenuItemOut.model_validate(i).model_dump(),
                    "recipe": _recipe_out(recipe_service.resolve_recipe(db, menu_item_id=i.id)),
                    "modifier_ids": sorted(str(m) for (mi, m) in links if mi == i.id),
                }
                for i in items
            ],
            "modifiers": [ModifierOut.model_validate(m).model_dump() for m in mods],
            "ingredients": [
                {"id": i.id, "name": i.name, "base_unit": i.base_unit, "kind": i.kind}
                for i in sorted(ingredients, key=lambda i: i.name)
                if i.kind in (IngredientKind.raw, IngredientKind.prep)
            ],
        }
    )
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    etag = '"' + hashlib.sha256(body.encode()).hexdigest()[:32] + '"'
    response.headers["ETag"] = etag
    if if_none_match == etag:
        # Device already has this exact catalogue: send nothing.
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    return Response(content=body, media_type="application/json", headers={"ETag": etag})
