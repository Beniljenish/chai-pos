"""Money from customers who paid online for a food court order (README, "9.14").

One account takes all of it (the app's single Razorpay account), so these belong to no
shop: an `OnlinePayment` is one Razorpay payment for one cart, which may cover several
outlets; `OnlineSettlement` is the food court operator paying an outlet its share.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin


class OnlinePayment(IdMixin, Base):
    """The same column names as `Payment` (a till bill's payment), on purpose: the
    Razorpay settle-and-capture code in services/payments.py works on either."""

    __tablename__ = "online_payments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'paid', 'failed')", name="ck_online_payments_status"
        ),
        CheckConstraint(
            "method IS NULL OR method IN ('upi', 'card')", name="ck_online_payments_method"
        ),
        CheckConstraint("amount_paise > 0", name="ck_online_payments_amount"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_accounts.id", ondelete="RESTRICT"), index=True
    )
    court_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food_courts.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(10), default="created", server_default="created")
    method: Mapped[str | None] = mapped_column(String(10))
    amount_paise: Mapped[int] = mapped_column(Integer)  # what was asked: every outlet's part added
    paid_paise: Mapped[int | None] = mapped_column(Integer)  # what Razorpay says arrived
    provider_order_id: Mapped[str] = mapped_column(String(40), unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    error: Mapped[str] = mapped_column(String(200), default="", server_default="")
    # One entry per outlet: what was ordered, what it cost, and later how it ended
    # (a token and status link, or why it could not be placed and whether it was refunded).
    parts: Mapped[list] = mapped_column(JSONB)
    message_ok: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Set once every part has been placed or refunded; a retry then changes nothing.
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_paise: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    refund_error: Mapped[str] = mapped_column(String(60), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OnlineSettlement(IdMixin, Base):
    """The operator paid an outlet some of what customers paid online on its behalf."""

    __tablename__ = "online_settlements"
    __table_args__ = (CheckConstraint("amount_paise > 0", name="ck_online_settlements_amount"),)

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="RESTRICT"), index=True
    )
    amount_paise: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(120), default="", server_default="")
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_admins.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
