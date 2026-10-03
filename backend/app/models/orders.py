"""Restaurant service: dining areas, tables, and running orders.

An order is a list of append-only events made on any device (offline too):
opened, a KOT of items, a line cancelled, moved table, bill printed, settled...
Its current state is computed from the events by one rule set, written in
services/orders.py and frontend/src/lib/orders.ts and pinned to each other by
shared/order_cases.json. The `orders` row keeps that computed state for queries.
Settling creates an ordinary Bill (the invoice) through the bill pipeline.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantScoped


class DiningArea(IdMixin, TenantScoped, Base):
    __tablename__ = "dining_areas"
    __table_args__ = (UniqueConstraint("shop_id", "name", name="uq_dining_areas_name"),)

    name: Mapped[str] = mapped_column(String(40))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class DiningTable(IdMixin, TenantScoped, Base):
    __tablename__ = "dining_tables"
    __table_args__ = (UniqueConstraint("shop_id", "name", name="uq_dining_tables_name"),)

    area_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dining_areas.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(20))  # "T4", "Patio 2"
    seats: Mapped[int] = mapped_column(Integer, default=4)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class OrderType(enum.StrEnum):
    dine_in = "dine_in"
    takeaway = "takeaway"
    delivery = "delivery"


class OrderStatus(enum.StrEnum):
    open = "open"  # taking orders
    billed = "billed"  # bill printed, waiting for payment
    settled = "settled"  # paid: the invoice exists
    cancelled = "cancelled"


class Order(TenantScoped, Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_shop_status", "shop_id", "status"),
        Index("ix_orders_shop_business_date", "shop_id", "business_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)  # from the device
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT")
    )
    order_type: Mapped[OrderType] = mapped_column(Enum(OrderType, name="order_type"))
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus, name="order_status"))
    table_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dining_tables.id", ondelete="RESTRICT"), index=True
    )
    opened_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    business_date: Mapped[date] = mapped_column(Date)
    # The computed state (services/orders.reduce): lines, KOTs, flags, bill id.
    state: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class OrderEventKind(enum.StrEnum):
    open = "open"
    kot = "kot"  # a round of items sent to the kitchen
    cancel = "cancel"  # some quantity of a line taken off, with a reason
    move = "move"  # to another table
    details = "details"  # covers, customer name / phone, note
    bill_printed = "bill_printed"  # the customer's bill (not yet the invoice)
    ready = "ready"  # the kitchen finished lines
    settle = "settle"  # paid: links the invoice (Bill)
    cancel_order = "cancel_order"


class OrderEvent(TenantScoped, Base):
    """Append-only. Never updated or deleted (see the migration's trigger)."""

    __tablename__ = "order_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)  # from the device
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[OrderEventKind] = mapped_column(Enum(OrderEventKind, name="order_event_kind"))
    data: Mapped[dict] = mapped_column(JSONB)
    by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT")
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # device clock
    content_hash: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
