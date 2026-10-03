"""Request/response shapes for Phase 1. Quantities are Decimals and are sent as
JSON strings ("555.556") so no precision is lost to JavaScript floats."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models import BaseUnit, IngredientKind, LedgerReason

Qty = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]
SignedQty = Annotated[Decimal, Field(max_digits=14, decimal_places=3)]
Name = Annotated[str, Field(min_length=1, max_length=80)]


# GST slabs since GST 2.0 (22 Sept 2025), in basis points: 0, 5, 18 and 40%.
# Restaurant and cafe service is 5% (no input tax credit). Anything else is
# almost certainly a typo (50 for 500), and a wrong rate prints on every bill.
GST_SLABS_BP = (0, 500, 1800, 4000)


def _gst_slab(v: int) -> int:
    if v not in GST_SLABS_BP:
        raise ValueError(
            "GST rate must be 0%, 5%, 18% or 40% (sent in basis points: 0, 500, 1800, 4000)"
        )
    return v


GstRate = Annotated[int, AfterValidator(_gst_slab)]
Scale = Annotated[Decimal, Field(gt=0, le=10, max_digits=6, decimal_places=3)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- ingredients & pack units ---
class PackUnitIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=30)]
    qty_in_base: Qty


class PackUnitOut(ORM):
    id: uuid.UUID
    name: str
    qty_in_base: Decimal


class IngredientCreate(BaseModel):
    name: Name
    kind: IngredientKind = IngredientKind.raw
    base_unit: BaseUnit
    tolerance_bp: Annotated[int, Field(ge=0, le=5000)] = 300
    count_frequency: Annotated[str, Field(pattern="^(shift|daily|weekly)$")] = "daily"
    reorder_level: Qty | None = None
    scales_with_size: bool = True  # False for cups, lids, straws
    pack_units: list[PackUnitIn] = []


class IngredientUpdate(BaseModel):
    name: Name | None = None
    tolerance_bp: Annotated[int, Field(ge=0, le=5000)] | None = None
    count_frequency: Annotated[str, Field(pattern="^(shift|daily|weekly)$")] | None = None
    reorder_level: Qty | None = None
    scales_with_size: bool | None = None
    is_active: bool | None = None


class IngredientOut(ORM):
    id: uuid.UUID
    name: str
    kind: IngredientKind
    base_unit: BaseUnit
    cost_per_unit_paise: Decimal
    tolerance_bp: int
    count_frequency: str
    reorder_level: Decimal | None
    scales_with_size: bool
    is_active: bool
    pack_units: list[PackUnitOut]


# --- menu items ---
class MenuItemCreate(BaseModel):
    name: Name
    category: Annotated[str, Field(min_length=1, max_length=40)] = "Tea"
    price_paise: Annotated[int, Field(ge=0, le=10_000_00)]
    gst_rate_bp: GstRate = 500  # restaurant service: 5% without ITC
    tax_inclusive: bool = True
    hsn_sac: Annotated[str, Field(pattern=r"^\d{4,8}$")] = "996331"


class MenuItemUpdate(BaseModel):
    name: Name | None = None
    category: Annotated[str, Field(min_length=1, max_length=40)] | None = None
    price_paise: Annotated[int, Field(ge=0, le=10_000_00)] | None = None
    gst_rate_bp: GstRate | None = None
    tax_inclusive: bool | None = None
    is_active: bool | None = None


class MenuItemOut(ORM):
    id: uuid.UUID
    name: str
    category: str
    price_paise: int
    gst_rate_bp: int
    tax_inclusive: bool
    hsn_sac: str
    is_active: bool


class ModifierIdsIn(BaseModel):
    modifier_ids: list[uuid.UUID]


# --- recipes ---
class RecipeLineIn(BaseModel):
    ingredient_id: uuid.UUID
    qty: Qty


class JuiceYield(BaseModel):
    ingredient_id: uuid.UUID
    ml_per_kg: Annotated[Decimal, Field(gt=0, le=1000)]
    portion_ml: Annotated[Decimal, Field(gt=0, le=2000)]


class MenuRecipeIn(BaseModel):
    lines: list[RecipeLineIn] = []
    juice_yield: JuiceYield | None = None


class PrepRecipeIn(BaseModel):
    lines: Annotated[list[RecipeLineIn], Field(min_length=1)]
    yield_qty: Qty


class RecipeLineOut(BaseModel):
    ingredient_id: uuid.UUID
    ingredient_name: str
    base_unit: BaseUnit
    qty: Decimal


class RecipeOut(BaseModel):
    id: uuid.UUID
    version: int
    effective_from: datetime
    yield_qty: Decimal | None
    yield_inputs: dict | None
    created_by_name: str | None = None  # filled in version history only
    lines: list[RecipeLineOut]


# --- modifiers ---
class ModifierLineIn(BaseModel):
    ingredient_id: uuid.UUID
    qty_delta: SignedQty


class ModifierCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=40)]
    price_delta_paise: Annotated[int, Field(ge=-100_00, le=100_00)] = 0
    scale_factor: Scale = Decimal(1)
    lines: list[ModifierLineIn] = []


class ModifierUpdate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=40)] | None = None
    price_delta_paise: Annotated[int, Field(ge=-100_00, le=100_00)] | None = None
    scale_factor: Scale | None = None
    lines: list[ModifierLineIn] | None = None
    is_active: bool | None = None


class ModifierLineOut(ORM):
    ingredient_id: uuid.UUID
    qty_delta: Decimal


class ModifierOut(ORM):
    id: uuid.UUID
    name: str
    price_delta_paise: int
    scale_factor: Decimal
    is_active: bool
    lines: list[ModifierLineOut]


# --- stock ---
class PackQtyIn(BaseModel):
    pack_unit_id: uuid.UUID
    qty: Qty


class StockInIn(BaseModel):
    ingredient_id: uuid.UUID
    packs: list[PackQtyIn] = []
    loose_qty: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)] = Decimal(0)
    cost_paise: Annotated[int, Field(ge=0, le=100_000_00)] = 0
    supplier: Annotated[str, Field(max_length=80)] = ""
    expiry_date: date | None = None
    confirm_large: bool = False


class StockReceiptOut(ORM):
    id: uuid.UUID
    ingredient_id: uuid.UUID
    entered: list
    loose_qty: Decimal
    base_qty: Decimal
    cost_paise: int
    supplier: str
    expiry_date: date | None
    business_date: date


class OpeningIn(BaseModel):
    ingredient_id: uuid.UUID
    packs: list[PackQtyIn] = []
    loose_qty: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)] = Decimal(0)


class OpeningOut(ORM):
    id: uuid.UUID
    ingredient_id: uuid.UUID
    counted_qty: Decimal
    system_qty: Decimal
    business_date: date


class PrepBatchIn(BaseModel):
    ingredient_id: uuid.UUID
    batches: Annotated[Decimal, Field(gt=0, le=100, max_digits=8, decimal_places=3)]


class PrepBatchOut(ORM):
    id: uuid.UUID
    recipe_id: uuid.UUID
    batches: Decimal
    business_date: date


class StockOut(BaseModel):
    ingredient_id: uuid.UUID
    name: str
    kind: IngredientKind
    base_unit: BaseUnit
    on_hand: Decimal
    is_negative: bool
    below_reorder: bool
    has_opening: bool
    is_active: bool


class LedgerOut(ORM):
    id: uuid.UUID
    qty_delta: Decimal
    reason: LedgerReason
    ref_type: str
    ref_id: uuid.UUID
    business_date: date
    created_at: datetime
