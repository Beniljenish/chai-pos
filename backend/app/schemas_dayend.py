"""Shapes for wastage and the day-end count. Quantities travel as strings."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from app.models import BaseUnit, DayCountStatus, IngredientKind, WastageReason
from app.schemas_catalogue import PackQtyIn, PackUnitOut, Qty

Loose = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]


class WastageIn(BaseModel):
    ingredient_id: uuid.UUID | None = None
    menu_item_id: uuid.UUID | None = None
    qty: Qty
    reason: WastageReason
    note: Annotated[str, Field(max_length=200)] = ""

    @model_validator(mode="after")
    def one_target(self):
        if (self.ingredient_id is None) == (self.menu_item_id is None):
            raise ValueError("Choose either an ingredient or a menu item")
        return self


class WastageOut(BaseModel):
    id: uuid.UUID
    name: str
    is_menu_item: bool
    qty: Decimal
    base_unit: BaseUnit | None
    reason: WastageReason
    note: str
    value_paise: int | None  # hidden from cashiers
    created_by_name: str
    created_at: datetime


class CountLineIn(BaseModel):
    ingredient_id: uuid.UUID
    packs: list[PackQtyIn] = []
    loose_qty: Loose = Decimal(0)


class CountsIn(BaseModel):
    lines: Annotated[list[CountLineIn], Field(min_length=1, max_length=200)]


class SubmitOut(BaseModel):
    status: DayCountStatus
    recount: list[uuid.UUID]  # count these again; deliberately no numbers


class SheetItem(BaseModel):
    ingredient_id: uuid.UUID
    name: str
    kind: IngredientKind
    base_unit: BaseUnit
    count_frequency: str
    pack_units: list[PackUnitOut]
    counted: bool
    recount: bool
    # Owner only. Never present for cashiers (the field is left out entirely):
    # a cashier who sees "should be 13.5 L" can type it without counting.
    expected: Decimal | None = None


class SheetOut(BaseModel):
    business_date: date
    status: DayCountStatus
    items: list[SheetItem]


class ReportLineOut(BaseModel):
    ingredient_id: uuid.UUID
    name: str
    base_unit: BaseUnit
    opening: Decimal
    stock_in: Decimal
    prep_in: Decimal
    prep_out: Decimal
    sold: Decimal
    wasted: Decimal
    other: Decimal
    expected: Decimal
    counted: Decimal
    variance: Decimal
    variance_paise: int
    cost_per_unit_paise: Decimal  # 0 = no purchase price yet, so no rupee value
    expected_usage: Decimal
    actual_usage: Decimal
    adherence_pct: Decimal | None
    tolerance_bp: int
    flagged: bool
    recounted: bool
    has_opening: bool


class ReportOut(BaseModel):
    business_date: date
    status: DayCountStatus
    submitted_by_name: str | None
    approved_by_name: str | None
    lines: list[ReportLineOut]
    missing_paise: int  # sum of shortfalls (negative variances), as a positive number
    surplus_paise: int
    flagged_count: int
    wastage_paise: int
    wastage_by_reason: dict[str, int]
    late_bills: int
    late_bills_explained_paise: int


class TrendPointOut(BaseModel):
    business_date: date
    adherence_pct: Decimal | None


class TrendLineOut(BaseModel):
    ingredient_id: uuid.UUID
    name: str
    base_unit: BaseUnit
    expected_usage: Decimal
    actual_usage: Decimal
    adherence_pct: Decimal | None
    variance_paise: int  # summed over the closed days
    points: list[TrendPointOut]


class AdherenceOut(BaseModel):
    start: date
    end: date
    closed_days: list[date]
    overall_pct: Decimal | None  # weighted by value
    lines: list[TrendLineOut]
