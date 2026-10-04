import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    # Reports by email. No address = no emails. Every bill is off by default:
    # a busy shop sends hundreds a day (provider limits, and it buries the rest).
    report_email: Mapped[str | None] = mapped_column(String(254))
    email_each_bill: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    email_day_end: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    email_daily: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    email_weekly: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Cash drawer shifts: on unless the shop has no cash drawer to check.
    cash_shifts: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # The most a cashier may take off a bill, in basis points of its value
    # (1000 = 10%). Over it, the bill is still saved and the owner sees it flagged.
    max_discount_bp: Mapped[int] = mapped_column(Integer, default=1000, server_default="1000")
    # A cashier's wastage worth more than this (paise, at cost) waits for the owner.
    wastage_approval_paise: Mapped[int] = mapped_column(
        Integer, default=20000, server_default="20000"
    )


class User(IdMixin, TimestampMixin, TenantScoped, Base):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(120))
    # Globally unique in v1 so login needs only phone + password.
    # Trade-off: one person cannot work at two shops with the same number.
    phone: Mapped[str] = mapped_column(String(15), unique=True)
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set when the owner sets someone's password (new staff, or a reset): the
    # owner knows it, so the person must choose their own before doing anything.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # Wrong-password lockout (see services/auth.py).
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def locked(self) -> bool:
        from app.core.time import utcnow  # local: core.time imports settings only

        return self.locked_until is not None and self.locked_until > utcnow()


class Device(IdMixin, TimestampMixin, TenantScoped, Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("shop_id", "code", name="uq_devices_shop_code"),)

    name: Mapped[str] = mapped_column(String(60))
    # Short code used in the per-device invoice series, e.g. "C1" -> C1/26-27/000123
    code: Mapped[str] = mapped_column(String(4))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The highest invoice sequence the tablet says it has PRINTED, per financial
    # year. Only ever goes up. A wiped tablet resumes after this, not after the
    # last bill the server received: those unsent numbers were already on paper.
    reported_seq_by_fy: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    # The tablet's last health report (outbox, rejections, storage), and when.
    health: Mapped[dict | None] = mapped_column(JSONB)
    health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    BillVoid,
    PaymentMode,
    VoidReason,
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
    StockOpening,
    StockReceipt,
)
from app.models.dayend import (  # noqa: E402
    OWNER_ONLY_REASONS,
    DayCount,
    DayCountLine,
    DayCountStatus,
    WastageEntry,
    WastageReason,
    WastageStatus,
)
from app.models.email import EmailKind, EmailOutbox, EmailStatus  # noqa: E402

__all__ = [
    "Bill",
    "BillLine",
    "BillLineModifier",
    "BillStatus",
    "BillVoid",
    "VoidReason",
    "PaymentMode",
    "BaseUnit",
    "DayCount",
    "DayCountLine",
    "DayCountStatus",
    "Device",
    "EmailKind",
    "EmailOutbox",
    "EmailStatus",
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
    "StockOpening",
    "StockReceipt",
    "User",
    "OWNER_ONLY_REASONS",
    "WastageEntry",
    "WastageReason",
    "WastageStatus",
]
from app.models.shifts import CashMovement, CashMovementKind, Shift  # noqa: E402

__all__ += ["CashMovement", "CashMovementKind", "Shift"]
from app.models.orders import (  # noqa: E402
    DiningArea,
    DiningTable,
    Order,
    OrderEvent,
    OrderEventKind,
    OrderStatus,
    OrderType,
)

__all__ += [
    "DiningArea",
    "DiningTable",
    "Order",
    "OrderEvent",
    "OrderEventKind",
    "OrderStatus",
    "OrderType",
]
from app.models.customers import CreditRepayment, Customer  # noqa: E402

__all__ += ["CreditRepayment", "Customer"]

from app.models.messages import Message  # noqa: E402

__all__ += ["Message"]

from app.models.payments import Payment  # noqa: E402

__all__ += ["Payment"]

from app.models.purchases import PurchaseOrder, PurchaseOrderLine, Supplier  # noqa: E402

__all__ += ["PurchaseOrder", "PurchaseOrderLine", "Supplier"]
