"""Phase 1: what the shop sells, what it is made of, and every stock movement.

Quantities are NUMERIC(14,3) in each ingredient's base unit (ml, g, piece):
exact decimals, so juice yields like 555.556 g of oranges per glass never
drift the way floats would. Money stays integer paise.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TenantScoped, TimestampMixin

QTY = Numeric(14, 3)


class IngredientKind(enum.StrEnum):
    raw = "raw"  # bought: milk, sugar, oranges
    prep = "prep"  # made in the shop in batches: tea decoction


class BaseUnit(enum.StrEnum):
    ml = "ml"
    g = "g"
    piece = "piece"


class LedgerReason(enum.StrEnum):
    opening = "opening"
    stock_in = "stock_in"
    sale = "sale"
    prep_in = "prep_in"
    prep_out = "prep_out"
    void = "void"
    wastage = "wastage"
    count_adjustment = "count_adjustment"


def _fk(target: str, ondelete: str = "RESTRICT"):
    return ForeignKey(target, ondelete=ondelete)


class Ingredient(IdMixin, TimestampMixin, TenantScoped, Base):
    __tablename__ = "ingredients"
    __table_args__ = (UniqueConstraint("shop_id", "name", name="uq_ingredients_shop_name"),)

    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[IngredientKind] = mapped_column(Enum(IngredientKind, name="ingredient_kind"))
    base_unit: Mapped[BaseUnit] = mapped_column(Enum(BaseUnit, name="base_unit"))
    # Paise per base unit; fractional because milk is ~6.4 paise per ml.
    cost_per_unit_paise: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal(0))
    tolerance_bp: Mapped[int] = mapped_column(Integer, default=300)  # 300 = +/-3%
    count_frequency: Mapped[str] = mapped_column(String(10), default="daily")
    reorder_level: Mapped[Decimal | None] = mapped_column(QTY)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # False for packaging (cups, lids, straws): one per serving whatever the size.
    # A "Large" modifier scales milk and fruit, never the number of cups. A larger
    # cup is a different ingredient, swapped in by the modifier's deltas.
    scales_with_size: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )

    pack_units: Mapped[list["PackUnit"]] = relationship(
        back_populates="ingredient", order_by="PackUnit.qty_in_base"
    )


class PackUnit(IdMixin, TenantScoped, Base):
    __tablename__ = "pack_units"
    __table_args__ = (
        UniqueConstraint("ingredient_id", "name", name="uq_pack_units_ingredient_name"),
        CheckConstraint("qty_in_base > 0", name="ck_pack_units_positive"),
    )

    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("ingredients.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(30))  # "packet", "crate"
    qty_in_base: Mapped[Decimal] = mapped_column(QTY)

    ingredient: Mapped[Ingredient] = relationship(back_populates="pack_units")


class MenuItem(IdMixin, TimestampMixin, TenantScoped, Base):
    __tablename__ = "menu_items"
    __table_args__ = (
        UniqueConstraint("shop_id", "name", name="uq_menu_items_shop_name"),
        CheckConstraint("price_paise >= 0", name="ck_menu_items_price"),
    )

    name: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(40), default="Tea")
    price_paise: Mapped[int] = mapped_column(Integer)
    hsn_sac: Mapped[str] = mapped_column(String(8), default="996331")  # restaurant service
    gst_rate_bp: Mapped[int] = mapped_column(Integer, default=500)  # 500 = 5%
    tax_inclusive: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Recipe(IdMixin, TenantScoped, Base):
    """One immutable version of an SOP. Editing a recipe inserts a new version.

    Exactly one of menu_item_id / prep_ingredient_id is set:
    - menu item recipe: what ONE unit sold consumes
    - prep recipe: what ONE batch consumes, and yield_qty = what one batch makes
    """

    __tablename__ = "recipes"
    __table_args__ = (
        CheckConstraint(
            "(menu_item_id IS NULL) <> (prep_ingredient_id IS NULL)",
            name="ck_recipes_one_output",
        ),
        CheckConstraint(
            "(prep_ingredient_id IS NULL) OR (yield_qty > 0)", name="ck_recipes_prep_yield"
        ),
        UniqueConstraint("menu_item_id", "version", name="uq_recipes_menu_item_version"),
        UniqueConstraint("prep_ingredient_id", "version", name="uq_recipes_prep_version"),
    )

    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), _fk("menu_items.id"), index=True
    )
    prep_ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), _fk("ingredients.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    yield_qty: Mapped[Decimal | None] = mapped_column(QTY)
    # How a juice line was derived, e.g. {"ingredient_id":..., "ml_per_kg":450, "portion_ml":250}
    yield_inputs: Mapped[dict | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["RecipeLine"]] = relationship(
        back_populates="recipe", order_by="RecipeLine.ingredient_id"
    )


class RecipeLine(IdMixin, TenantScoped, Base):
    __tablename__ = "recipe_lines"
    __table_args__ = (
        UniqueConstraint("recipe_id", "ingredient_id", name="uq_recipe_lines_ingredient"),
        CheckConstraint("qty > 0", name="ck_recipe_lines_positive"),
    )

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("recipes.id", "CASCADE"), index=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("ingredients.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)

    recipe: Mapped[Recipe] = relationship(back_populates="lines")
    ingredient: Mapped[Ingredient] = relationship()


class Modifier(IdMixin, TimestampMixin, TenantScoped, Base):
    __tablename__ = "modifiers"
    __table_args__ = (
        UniqueConstraint("shop_id", "name", name="uq_modifiers_shop_name"),
        CheckConstraint("scale_factor > 0", name="ck_modifiers_scale"),
    )

    name: Mapped[str] = mapped_column(String(40))
    price_delta_paise: Mapped[int] = mapped_column(Integer, default=0)
    scale_factor: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=Decimal(1))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    lines: Mapped[list["ModifierLine"]] = relationship(
        back_populates="modifier", cascade="all, delete-orphan"
    )


class ModifierLine(IdMixin, TenantScoped, Base):
    __tablename__ = "modifier_lines"
    __table_args__ = (
        UniqueConstraint("modifier_id", "ingredient_id", name="uq_modifier_lines_ingredient"),
    )

    modifier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("modifiers.id", "CASCADE"), index=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("ingredients.id"))
    qty_delta: Mapped[Decimal] = mapped_column(QTY)  # negative = uses less

    modifier: Mapped[Modifier] = relationship(back_populates="lines")


class MenuItemModifier(IdMixin, TenantScoped, Base):
    __tablename__ = "menu_item_modifiers"
    __table_args__ = (
        UniqueConstraint("menu_item_id", "modifier_id", name="uq_menu_item_modifiers"),
    )

    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("menu_items.id", "CASCADE"), index=True
    )
    modifier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("modifiers.id", "CASCADE")
    )


class StockReceipt(IdMixin, TenantScoped, Base):
    """Stock-in exactly as entered ("3 crates + 4 packets") and as converted."""

    __tablename__ = "stock_receipts"
    __table_args__ = (CheckConstraint("base_qty > 0", name="ck_stock_receipts_positive"),)

    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("ingredients.id"), index=True
    )
    supplier: Mapped[str] = mapped_column(String(80), default="")
    entered: Mapped[list] = mapped_column(JSONB)  # [{"pack_unit_id","name","qty","qty_in_base"}]
    loose_qty: Mapped[Decimal] = mapped_column(QTY, default=Decimal(0))
    base_qty: Mapped[Decimal] = mapped_column(QTY)
    cost_paise: Mapped[int] = mapped_column(Integer, default=0)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    business_date: Mapped[date] = mapped_column(Date)
    received_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users.id"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StockOpening(IdMixin, TenantScoped, Base):
    """The first physical count of an ingredient: the starting point for variance.

    Once per ingredient (unique). Re-entering "opening stock" whenever numbers
    look wrong would silently absorb losses, which is what variance exists to
    catch. After this, every change needs a reason (stock-in, sale, wastage,
    day-end count). The ledger row is the adjustment from what the system
    thought was there; it is skipped when that adjustment is exactly zero.
    """

    __tablename__ = "stock_openings"
    __table_args__ = (
        UniqueConstraint("shop_id", "ingredient_id", name="uq_stock_openings_ingredient"),
        CheckConstraint("counted_qty >= 0", name="ck_stock_openings_counted"),
    )

    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("ingredients.id"))
    entered: Mapped[list] = mapped_column(JSONB)  # same shape as stock_receipts.entered
    loose_qty: Mapped[Decimal] = mapped_column(QTY, default=Decimal(0))
    counted_qty: Mapped[Decimal] = mapped_column(QTY)
    system_qty: Mapped[Decimal] = mapped_column(QTY)  # what the ledger said before
    business_date: Mapped[date] = mapped_column(Date)
    counted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users.id"))
    counted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PrepBatch(IdMixin, TenantScoped, Base):
    __tablename__ = "prep_batches"
    __table_args__ = (CheckConstraint("batches > 0", name="ck_prep_batches_positive"),)

    recipe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("recipes.id"))
    batches: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    business_date: Mapped[date] = mapped_column(Date)
    made_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users.id"))
    made_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StockLedger(IdMixin, TenantScoped, Base):
    """Append-only. A Postgres trigger rejects UPDATE and DELETE.
    Stock on hand for an ingredient = SUM(qty_delta)."""

    __tablename__ = "stock_ledger"
    __table_args__ = (
        Index("ix_stock_ledger_shop_ingredient", "shop_id", "ingredient_id"),
        CheckConstraint("qty_delta <> 0", name="ck_stock_ledger_nonzero"),
    )

    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("ingredients.id"))
    qty_delta: Mapped[Decimal] = mapped_column(QTY)
    reason: Mapped[LedgerReason] = mapped_column(Enum(LedgerReason, name="ledger_reason"))
    ref_type: Mapped[str] = mapped_column(String(30))  # "stock_receipt", "prep_batch", ...
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    business_date: Mapped[date] = mapped_column(Date, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
