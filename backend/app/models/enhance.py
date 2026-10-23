"""Customer-side extras for food courts (README, "9.15"): ratings, favourites and the phones that
asked to be told when an order is ready."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
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


class Coupon(IdMixin, TenantScoped, Base):
    """An offer one outlet makes: a code that takes a percentage or a fixed amount off an online
    order. The outlet pays for it (it is the outlet's own revenue given up); the food court's fee
    and its statements are worked out on what the customer actually paid."""

    __tablename__ = "coupons"
    __table_args__ = (
        UniqueConstraint("shop_id", "code", name="uq_coupons_code"),
        CheckConstraint("kind IN ('percent', 'amount')", name="ck_coupons_kind"),
        CheckConstraint("value > 0", name="ck_coupons_value"),
    )

    code: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(10))
    # percent: 1 to 100; amount: paise
    value: Mapped[int] = mapped_column(Integer)
    min_order_paise: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # For a percentage: the most it may take off (null = no cap).
    max_discount_paise: Mapped[int | None] = mapped_column(Integer)
    valid_until: Mapped[date | None] = mapped_column(Date)  # last day it works; null = no end
    max_uses: Mapped[int | None] = mapped_column(Integer)  # in all; null = unlimited
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # A loyalty reward belongs to one customer; null = an ordinary offer anyone can use.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_accounts.id", ondelete="CASCADE"), index=True
    )


class CouponRedemption(IdMixin, TenantScoped, Base):
    """One use of a coupon on one order. A cancelled order's use is not counted."""

    __tablename__ = "coupon_redemptions"
    __table_args__ = (UniqueConstraint("order_id", name="uq_coupon_redemptions_order"),)

    coupon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coupons.id", ondelete="RESTRICT"), index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT")
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_accounts.id", ondelete="RESTRICT"), index=True
    )
    discount_paise: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SoldOutEvent(IdMixin, TenantScoped, Base):
    """A dish was switched "sold out" by the owner (README, "9.19"): the history behind
    "sold out most". Dishes hidden by the stock check are not recorded: nobody switched them."""

    __tablename__ = "sold_out_events"

    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="RESTRICT"), index=True
    )
    business_date: Mapped[date] = mapped_column(Date, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserLink(IdMixin, Base):
    """Two owner logins, in two shops, that belong to the same person (README, "9.19"). Made only
    by someone who proved both passwords, and stored both ways. It lets the owner see an overview
    of every linked outlet from one login; it does not let anyone act inside another shop, and no
    token is ever issued from it."""

    __tablename__ = "user_links"
    __table_args__ = (UniqueConstraint("user_id", "linked_user_id", name="uq_user_links_pair"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    linked_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Attendance(IdMixin, TenantScoped, Base):
    """One stretch of work: clocked in, and (later) out. Written on the server when the person
    taps clock in/out on the till, so it needs a connection; the owner can correct a mistake."""

    __tablename__ = "attendance"
    __table_args__ = (
        CheckConstraint(
            "clock_out_at IS NULL OR clock_out_at >= clock_in_at", name="ck_attendance_order"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    business_date: Mapped[date] = mapped_column(Date, index=True)
    clock_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    clock_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(String(120), default="", server_default="")
    # Set when the owner corrected this entry (who, and when).
    edited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SpecialDay(IdMixin, TenantScoped, Base):
    """A day the owner expects to be different (a festival), to look back at last year's."""

    __tablename__ = "special_days"
    __table_args__ = (UniqueConstraint("shop_id", "day", "name", name="uq_special_days"),)

    day: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[str] = mapped_column(String(60))


class AuditEvent(IdMixin, TenantScoped, Base):
    """Who changed something that matters (a price, a recipe, an offer, a person, GST settings).
    Append-only: a database trigger refuses any update or delete."""

    __tablename__ = "audit_events"

    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(String(40))
    subject: Mapped[str] = mapped_column(String(120))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)


class GroupCart(IdMixin, Base):
    """Order together (README, "9.21"): friends in one food court add their own dishes to a
    shared list and the host pays for it. It belongs to customers, not to a shop, so it is not
    tenant-scoped; it only ever holds ids and quantities, never prices or phone numbers."""

    __tablename__ = "group_carts"

    token: Mapped[str] = mapped_column(String(16), unique=True)
    court_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food_courts.id", ondelete="CASCADE"), index=True
    )
    host_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_accounts.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GroupMember(IdMixin, Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "customer_id", name="uq_group_members"),)

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("group_carts.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_accounts.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(40))  # what the others see: the name, nothing else
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GroupLine(IdMixin, Base):
    __tablename__ = "group_lines"
    __table_args__ = (CheckConstraint("qty BETWEEN 1 AND 20", name="ck_group_lines_qty"),)

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("group_carts.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_accounts.id", ondelete="CASCADE")
    )
    outlet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))  # a food_court_outlets id
    menu_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    modifier_ids: Mapped[list] = mapped_column(JSONB, default=list)
    qty: Mapped[int] = mapped_column(Integer)


class AppError(IdMixin, Base):
    """Something that broke, on the server or in someone's app (README, "9.28"). Kept 30 days
    for the platform admin to read. Never holds a phone number or a password: text is scrubbed
    before it is written."""

    __tablename__ = "app_errors"

    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    source: Mapped[str] = mapped_column(String(10))  # "server" or "app"
    shop_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    place: Mapped[str] = mapped_column(String(200), default="", server_default="")
    message: Mapped[str] = mapped_column(String(500))
    detail: Mapped[str] = mapped_column(String(4000), default="", server_default="")
    agent: Mapped[str] = mapped_column(String(200), default="", server_default="")
