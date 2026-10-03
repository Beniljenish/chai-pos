"""Phase 2: bills. A bill is written once, never edited (voids come in Phase 3).

Two sets of totals are stored:
- the PRINTED totals (what the device calculated and handed to the customer).
  These are the legal invoice and what the books record.
- server_totals: what the server's own GST code calculates from the same lines.
If they differ, totals_mismatch is set and the owner reviews it.
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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantScoped
from app.models import GstType


class PaymentMode(enum.StrEnum):
    cash = "cash"
    upi = "upi"
    card = "card"


class BillStatus(enum.StrEnum):
    completed = "completed"
    void = "void"  # Phase 3


class Bill(TenantScoped, Base):
    __tablename__ = "bills"
    __table_args__ = (
        # One invoice number per shop, ever; and one sequence slot per device per FY.
        UniqueConstraint("shop_id", "invoice_no", name="uq_bills_invoice_no"),
        UniqueConstraint("shop_id", "device_id", "fy", "local_seq", name="uq_bills_device_seq"),
        Index("ix_bills_shop_business_date", "shop_id", "business_date"),
        CheckConstraint("local_seq >= 1", name="ck_bills_seq"),
        CheckConstraint("total_paise >= 0", name="ck_bills_total"),
    )

    # Generated on the device (UUIDv7) and used as the idempotency key.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT"), index=True
    )
    cashier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    fy: Mapped[str] = mapped_column(String(5))  # "26-27"
    local_seq: Mapped[int] = mapped_column(Integer)
    invoice_no: Mapped[str] = mapped_column(String(16))  # "C1/26-27/000123"
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # device clock
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    business_date: Mapped[date] = mapped_column(Date)
    payment_mode: Mapped[PaymentMode] = mapped_column(Enum(PaymentMode, name="payment_mode"))
    status: Mapped[BillStatus] = mapped_column(
        Enum(BillStatus, name="bill_status"), default=BillStatus.completed
    )
    gst_type: Mapped[GstType] = mapped_column(Enum(GstType, name="gst_type", create_type=False))

    # As printed (the legal record)
    taxable_paise: Mapped[int] = mapped_column(Integer)
    cgst_paise: Mapped[int] = mapped_column(Integer)
    sgst_paise: Mapped[int] = mapped_column(Integer)
    subtotal_paise: Mapped[int] = mapped_column(Integer)
    round_off_paise: Mapped[int] = mapped_column(Integer)
    total_paise: Mapped[int] = mapped_column(Integer)

    # The server's independent calculation, and whether it disagreed
    server_totals: Mapped[dict] = mapped_column(JSONB)
    totals_mismatch: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # sha256 of the bill as received: same id + same hash = harmless retry,
    # same id + different hash = a bug or tampering.
    content_hash: Mapped[str] = mapped_column(String(64))

    lines: Mapped[list["BillLine"]] = relationship(
        back_populates="bill", order_by="BillLine.position", cascade="all, delete-orphan"
    )


class BillLine(TenantScoped, Base):
    __tablename__ = "bill_lines"
    __table_args__ = (
        UniqueConstraint("bill_id", "position", name="uq_bill_lines_position"),
        CheckConstraint("qty >= 1", name="ck_bill_lines_qty"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bills.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="RESTRICT")
    )
    # The recipe version the device sold under; NULL if the item had no recipe.
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="RESTRICT")
    )
    name_snapshot: Mapped[str] = mapped_column(String(80))
    unit_price_paise: Mapped[int] = mapped_column(Integer)
    qty: Mapped[int] = mapped_column(Integer)
    gst_rate_bp: Mapped[int] = mapped_column(Integer)
    tax_inclusive: Mapped[bool] = mapped_column(Boolean)
    # As printed
    gross_paise: Mapped[int] = mapped_column(Integer)
    taxable_paise: Mapped[int] = mapped_column(Integer)
    cgst_paise: Mapped[int] = mapped_column(Integer)
    sgst_paise: Mapped[int] = mapped_column(Integer)
    total_paise: Mapped[int] = mapped_column(Integer)

    bill: Mapped[Bill] = relationship(back_populates="lines")
    modifiers: Mapped[list["BillLineModifier"]] = relationship(cascade="all, delete-orphan")


class BillLineModifier(TenantScoped, Base):
    """Snapshot of a modifier's effect as the device applied it. Modifiers are not
    versioned, so the bill keeps its own copy of what "Less sugar" meant that day."""

    __tablename__ = "bill_line_modifiers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bill_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bill_lines.id", ondelete="CASCADE"), index=True
    )
    modifier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("modifiers.id", ondelete="RESTRICT")
    )
    name_snapshot: Mapped[str] = mapped_column(String(40))
    price_delta_paise: Mapped[int] = mapped_column(Integer)
    scale_factor: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    lines_snapshot: Mapped[list] = mapped_column(JSONB)  # [{"ingredient_id","qty_delta"}]
