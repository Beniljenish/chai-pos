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
    Integer,
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
    # Where it is ("Marina Beach, Chennai"): what a customer picks a court by.
    location: Mapped[str] = mapped_column(String(120), default="", server_default="")
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
    # The outlet's own promise of how long an order usually takes (null = not said).
    prep_minutes: Mapped[int | None] = mapped_column(Integer)
    # What the food court operator keeps of every online sale, in basis points (500 = 5%).
    fee_bp: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Customers may order for a time later today; at most this many orders per 15-minute slot.
    pickup_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    pickup_capacity: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    # "Pause when busy": this many open online orders pauses new ones for ten minutes by itself.
    busy_pause_on: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    busy_limit: Mapped[int] = mapped_column(Integer, default=12, server_default="12")
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Loyalty: every `loyalty_every`-th order a customer places here earns a personal reward of
    # `loyalty_reward_paise` off their next one (both null = off).
    loyalty_every: Mapped[int | None] = mapped_column(Integer)
    loyalty_reward_paise: Mapped[int | None] = mapped_column(Integer)
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
    # When the customer was told it is ready (a push notification), so it is sent only once.
    ready_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Paid online (README, "9.14"): the Razorpay payment this order was part of, and how much of
    # it is this outlet's. Both null for an order to be paid at the counter.
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("online_payments.id", ondelete="RESTRICT"), index=True
    )
    paid_paise: Mapped[int | None] = mapped_column(Integer)
    refunded_paise: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Whose order it is. Null only for orders placed before accounts existed.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_accounts.id", ondelete="RESTRICT"), index=True
    )
    business_date: Mapped[date] = mapped_column(Date, index=True)
    # A time the customer asked for ("1:00 pm"); null = as soon as possible.
    pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The table the customer scanned, for dine-in ("T4"); empty = a takeaway order.
    table_name: Mapped[str] = mapped_column(String(20), default="", server_default="")
    # An offer the customer used: the code, and the paise taken off the total (0 = none). The
    # till bills the order with the same discount, so the bill equals what the customer owes.
    coupon_code: Mapped[str] = mapped_column(String(20), default="", server_default="")
    discount_paise: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
