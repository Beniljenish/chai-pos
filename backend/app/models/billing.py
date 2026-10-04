"""Bills. A bill is written once, never edited; a void is a separate record (BillVoid)
and the only change to the bill row is its status flag.

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
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TenantScoped
from app.models import GstType


class PaymentMode(enum.StrEnum):
    cash = "cash"
    upi = "upi"
    card = "card"
    split = "split"  # several parts (cash + UPI, or part on credit): see payment_parts
    credit = "credit"  # the whole bill on the customer's khata


class BillStatus(enum.StrEnum):
    completed = "completed"
    void = "void"  # set only together with a BillVoid row


class VoidReason(enum.StrEnum):
    wrong_item = "wrong_item"  # tapped the wrong drink; nothing was made
    duplicate = "duplicate"  # same order billed twice
    payment_failed = "payment_failed"  # UPI did not go through, customer left
    customer_cancelled = "customer_cancelled"
    other = "other"


class Bill(TenantScoped, Base):
    __tablename__ = "bills"
    __table_args__ = (
        # One invoice number per shop, ever; and one sequence slot per device per FY.
        UniqueConstraint("shop_id", "invoice_no", name="uq_bills_invoice_no"),
        UniqueConstraint("shop_id", "device_id", "fy", "local_seq", name="uq_bills_device_seq"),
        Index("ix_bills_shop_business_date", "shop_id", "business_date"),
        CheckConstraint("local_seq >= 1", name="ck_bills_seq"),
        CheckConstraint("total_paise >= 0", name="ck_bills_total"),
        # One invoice per order PART (a table may split its bill into several):
        # a second settle of the same part from another tablet is refused. Same
        # name as before Phase 6, so code that recognises it keeps working.
        Index(
            "uq_bills_order_id",
            "order_id",
            "order_part",
            unique=True,
            postgresql_where=text("order_id IS NOT NULL"),
        ),
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
    # The drawer shift it was rung up in (NULL: older app, or shifts switched off).
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id", ondelete="RESTRICT"), index=True
    )
    # The running order this bill settled (restaurant service), if any.
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT")
    )
    # Which part of a split order this invoice is (1 when not split).
    order_part: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    status: Mapped[BillStatus] = mapped_column(
        Enum(BillStatus, name="bill_status"), default=BillStatus.completed
    )
    # Phase 6. All discounts on the bill (line discounts and the bill discount),
    # and why; how it was paid when not in one mode ([{"mode", "paise"}]); whose
    # khata a credit part goes on.
    discount_paise: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    discount_reason: Mapped[str] = mapped_column(String(200), default="", server_default="")
    payment_parts: Mapped[list | None] = mapped_column(JSONB)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    # Things the owner should look at; the bill still stands as printed:
    # discount_over_limit, discount_without_reason, payment_parts_mismatch,
    # credit_without_customer.
    flags: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
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
    void: Mapped["BillVoid | None"] = relationship(uselist=False, viewonly=True)


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
    # The line's own discount plus its share of the bill discount (Phase 6).
    discount_paise: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
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


class BillVoid(IdMixin, TenantScoped, Base):
    """The owner cancelled a bill. The invoice number stays used (GST: no gaps in the
    series); the bill drops out of sales; its stock comes back unless the drink
    was already made. One per bill, never removed."""

    __tablename__ = "bill_voids"
    __table_args__ = (UniqueConstraint("bill_id", name="uq_bill_voids_bill"),)

    bill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bills.id", ondelete="RESTRICT")
    )
    reason: Mapped[VoidReason] = mapped_column(Enum(VoidReason, name="void_reason"))
    note: Mapped[str] = mapped_column(String(200), default="")
    stock_returned: Mapped[bool] = mapped_column(Boolean)
    voided_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    voided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", viewonly=True)

    @property
    def voided_by_name(self) -> str:
        return self.user.name if self.user else ""
