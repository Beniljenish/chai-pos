"""Online payments (Razorpay), linked to a bill (README, "Phase 8a").

A bill is written on the tablet first and is the legal record; an online payment
is a separate row that says whether the customer's money actually arrived. One
row per Razorpay order; the bill's total is never changed by a payment, and an
amount that differs is flagged, not corrected.

Status: created (order made, customer not done yet) -> paid, or -> failed (the
last attempt failed; the customer may still try again on the same order, so
failed can still become paid). Paid is final.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantScoped, TimestampMixin

PAYMENT_STATUSES = ("created", "paid", "failed")
PAYMENT_METHODS = ("upi", "card")


class Payment(IdMixin, TimestampMixin, TenantScoped, Base):
    __tablename__ = "payments"
    __table_args__ = (
        # Plain strings with checks, not Postgres enums: a new provider or status
        # later is a one-line change, not an ALTER TYPE that cannot be undone.
        CheckConstraint("status IN ('created', 'paid', 'failed')", name="ck_payments_status"),
        CheckConstraint("method IN ('upi', 'card')", name="ck_payments_method"),
        CheckConstraint("amount_paise > 0", name="ck_payments_amount"),
    )

    bill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bills.id", ondelete="RESTRICT"), index=True
    )
    provider: Mapped[str] = mapped_column(String(20), default="razorpay")
    method: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), default="created")
    amount_paise: Mapped[int] = mapped_column(Integer)  # what was asked for: the bill total
    paid_paise: Mapped[int | None] = mapped_column(Integer)  # what Razorpay says arrived
    # Razorpay's ids. Unique: a webhook or a verify call arriving twice finds the
    # same row, so recording a payment is idempotent.
    provider_order_id: Mapped[str] = mapped_column(String(40), unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    error: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
