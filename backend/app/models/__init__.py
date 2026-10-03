import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantScoped, TimestampMixin


class GstType(enum.StrEnum):
    regular = "regular"
    composition = "composition"
    unregistered = "unregistered"


class Role(enum.StrEnum):
    owner = "owner"
    cashier = "cashier"


class Shop(IdMixin, TimestampMixin, Base):
    """The tenant root. Not TenantScoped itself: access is always by ctx.shop_id."""

    __tablename__ = "shops"

    name: Mapped[str] = mapped_column(String(120))
    gst_type: Mapped[GstType] = mapped_column(
        Enum(GstType, name="gst_type"), default=GstType.unregistered
    )
    gstin: Mapped[str | None] = mapped_column(String(15))
    state_code: Mapped[str] = mapped_column(String(2))  # e.g. "33" = Tamil Nadu
    address: Mapped[str] = mapped_column(String(500), default="")
    invoice_prefix: Mapped[str] = mapped_column(String(4), default="")


class User(IdMixin, TimestampMixin, TenantScoped, Base):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(120))
    # Globally unique in v1 so login needs only phone + password.
    # Trade-off: one person cannot work at two shops with the same number.
    phone: Mapped[str] = mapped_column(String(15), unique=True)
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Device(IdMixin, TimestampMixin, TenantScoped, Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("shop_id", "code", name="uq_devices_shop_code"),)

    name: Mapped[str] = mapped_column(String(60))
    # Short code used in the per-device invoice series, e.g. "C1" -> C1/26-27/000123
    code: Mapped[str] = mapped_column(String(4))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(IdMixin, TenantScoped, Base):
    """Stored hashed, so a database leak does not leak usable tokens."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # All tokens produced by rotating one login share a family; reuse of a
    # revoked token revokes the whole family (stolen-token detection).
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# Phase 1 tables live in their own module; re-exported so `from app.models import X` works.
from app.models.billing import (  # noqa: E402
    Bill,
    BillLine,
    BillLineModifier,
    BillStatus,
    PaymentMode,
)
from app.models.catalogue import (  # noqa: E402
    BaseUnit,
    Ingredient,
    IngredientKind,
    LedgerReason,
    MenuItem,
    MenuItemModifier,
    Modifier,
    ModifierLine,
    PackUnit,
    PrepBatch,
    Recipe,
    RecipeLine,
    StockLedger,
    StockReceipt,
)

__all__ = [
    "Bill",
    "BillLine",
    "BillLineModifier",
    "BillStatus",
    "PaymentMode",
    "BaseUnit",
    "Device",
    "GstType",
    "Ingredient",
    "IngredientKind",
    "LedgerReason",
    "MenuItem",
    "MenuItemModifier",
    "Modifier",
    "ModifierLine",
    "PackUnit",
    "PrepBatch",
    "Recipe",
    "RecipeLine",
    "RefreshToken",
    "Role",
    "Shop",
    "StockLedger",
    "StockReceipt",
    "User",
]
