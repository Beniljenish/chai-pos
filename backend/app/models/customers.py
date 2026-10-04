"""Customers and their khata (credit) (README, "Phase 6").

A customer is made on the tablet, offline if need be, the first time a number is
used for a credit bill or saved on a bill; the server keeps ONE customer per
phone number per shop, so two tablets that each made "Priya" end up with the
same khata. The number is personal data: it is stored here and on the order it
was given for, and nowhere else.

What a customer owes is computed, never stored: credit parts of their bills that
are not void, minus repayments. Repayments are rows, never edited.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped


class Customer(TenantScoped, Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("shop_id", "phone", name="uq_customers_phone"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)  # from a tablet
    phone: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CreditRepayment(TenantScoped, Base):
    __tablename__ = "credit_repayments"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_credit_repayments_amount"),
        CheckConstraint("mode IN ('cash', 'upi', 'card')", name="ck_credit_repayments_mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)  # from a tablet
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    amount_paise: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(10))
    # Cash repaid at the counter goes into that drawer shift's expected cash.
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id", ondelete="RESTRICT"), index=True
    )
    received_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    note: Mapped[str] = mapped_column(String(200), default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    business_date: Mapped[date] = mapped_column(Date, index=True)
