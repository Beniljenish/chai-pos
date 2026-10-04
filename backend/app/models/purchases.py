"""Suppliers and purchase orders (README, "Phase 7").

A purchase order is what the owner asked a supplier for. Receiving it records
what actually came, at what cost, as ordinary stock-in receipts: the stock
ledger stays the one place stock moves, and an order changes nothing in stock
until it is received. Status: open -> received, or open -> cancelled.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TenantScoped

QTY = Numeric(14, 3)  # base units, like the stock ledger


class Supplier(IdMixin, TenantScoped, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(15), default="")
    note: Mapped[str] = mapped_column(String(200), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PurchaseOrder(IdMixin, TenantScoped, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'received', 'cancelled')", name="ck_purchase_orders_status"
        ),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(10), default="open")
    note: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        order_by="PurchaseOrderLine.position", cascade="all, delete-orphan"
    )


class PurchaseOrderLine(IdMixin, TenantScoped, Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_purchase_order_lines_qty"),
        CheckConstraint("received_qty >= 0", name="ck_purchase_order_lines_received"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id", ondelete="RESTRICT")
    )
    qty: Mapped[Decimal] = mapped_column(QTY)  # ordered, in base units
    expected_cost_paise: Mapped[int] = mapped_column(Integer, default=0)
    # Filled in when received: what came, what it cost, and the stock receipt made.
    received_qty: Mapped[Decimal | None] = mapped_column(QTY)
    cost_paise: Mapped[int | None] = mapped_column(Integer)
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_receipts.id", ondelete="RESTRICT")
    )
