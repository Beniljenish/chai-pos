"""Customer-side extras for food courts (README, "9.15"): ratings, favourites and the phones that
asked to be told when an order is ready."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantScoped


class OrderFeedback(IdMixin, TenantScoped, Base):
    """One customer's 1 to 5 rating of one collected online order. Belongs to the outlet's shop,
    so its owner reads it through the ordinary shop rules."""

    __tablename__ = "order_feedback"
    __table_args__ = (
        UniqueConstraint("online_order_id", name="uq_order_feedback_order"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_order_feedback_rating"),
    )

    online_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("online_orders.id", ondelete="RESTRICT")
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_accounts.id", ondelete="RESTRICT"), index=True
    )
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(String(200), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CustomerFavourite(IdMixin, Base):
    """A dish a customer hearted. Belongs to the customer, not to a shop (it has the shop's id
    only so the dish can be found again), so it is not tenant-scoped."""

    __tablename__ = "customer_favourites"
    __table_args__ = (
        UniqueConstraint("customer_id", "menu_item_id", name="uq_customer_favourite"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_accounts.id", ondelete="CASCADE"), index=True
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE")
    )
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PushSubscription(IdMixin, Base):
    """A browser that asked to be notified (Web Push). The endpoint is the browser's own address
    for it; it is unique, so subscribing twice is one row."""

    __tablename__ = "push_subscriptions"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_accounts.id", ondelete="CASCADE"), index=True
    )
    endpoint: Mapped[str] = mapped_column(String(600), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiUsage(IdMixin, TenantScoped, Base):
    """How many AI calls a shop made on one business day, so a day has a ceiling."""

    __tablename__ = "ai_usage"
    __table_args__ = (UniqueConstraint("shop_id", "day", name="uq_ai_usage_shop_day"),)

    day: Mapped[date] = mapped_column(Date)
    calls: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class PhoneCode(IdMixin, Base):
    """A 6-digit code sent to a mobile number (sign-up check, forgot password). Belongs to no
    shop. Only a hash is kept; it expires, allows a few wrong tries, and works once."""

    __tablename__ = "phone_codes"

    phone: Mapped[str] = mapped_column(String(15), index=True)
    purpose: Mapped[str] = mapped_column(String(10))  # "signup" | "reset"
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RateHit(IdMixin, Base):
    """One counted event for a rate limit (a sign-up from an address, a code sent to a number)."""

    __tablename__ = "rate_hits"

    key: Mapped[str] = mapped_column(String(120), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DishPhoto(IdMixin, TenantScoped, Base):
    """A picture an outlet took of a dish, kept in the database (shrunk by the phone first)."""

    __tablename__ = "dish_photos"

    content_type: Mapped[str] = mapped_column(String(20))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
