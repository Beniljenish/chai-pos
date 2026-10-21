"""Customer-side extras for food courts (README, "9.15"): ratings, favourites and the phones that
asked to be told when an order is ready."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
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
