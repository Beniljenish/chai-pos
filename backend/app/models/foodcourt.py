"""Food courts: several outlets (each its own shop) that customers order from by
scanning one QR (README, "9.11").

A food court and its outlet list belong to no single shop, so FoodCourt and
FoodCourtOutlet are deliberately NOT TenantScoped: the shop an outlet row names
is checked by hand wherever they are read (services/online.py), never inferred.
OnlineOrder is the opposite: a note, inside one shop, that an order came from a
customer scanning the QR, with its token. The order itself is an ordinary
takeaway Order.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantScoped


class FoodCourt(IdMixin, Base):
    __tablename__ = "food_courts"

    name: Mapped[str] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(String(60), unique=True)  # the public address
    # RETIRED: outlets were first invited by a code, before the super admin existed.
    # Kept (unused) so removing it can be a later, separate step.
    join_code: Mapped[str | None] = mapped_column(String(12))
    host_shop_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="RESTRICT")
    )
    # The super admin who made it (a food court belongs to no shop).
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_admins.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FoodCourtOutlet(IdMixin, Base):
    __tablename__ = "food_court_outlets"
    # A shop is in at most one food court.
    __table_args__ = (UniqueConstraint("shop_id", name="uq_food_court_outlets_shop"),)

    court_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food_courts.id", ondelete="RESTRICT"), index=True
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="RESTRICT")
    )
    # Off until the outlet's own owner switches it on.
    accepting_orders: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OnlineOrder(IdMixin, TenantScoped, Base):
    __tablename__ = "online_orders"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_online_orders_order"),
        UniqueConstraint("shop_id", "business_date", "token", name="uq_online_orders_token"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT")
    )
    court_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food_courts.id", ondelete="RESTRICT")
    )
    token: Mapped[str] = mapped_column(String(12))  # "JT-17": what the customer shows
    business_date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
