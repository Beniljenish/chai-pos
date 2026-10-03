"""Shifts and the cash drawer.

A shift belongs to one tablet (one drawer) and one person. It is started on the
tablet, offline if need be, and synced like bills (the id is made on the tablet,
so a retry is harmless). Bills carry their shift's id, so the drawer is checked
against exactly the bills rung up in that shift.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped


class Shift(TenantScoped, Base):
    __tablename__ = "shifts"
    __table_args__ = (
        Index("ix_shifts_shop_business_date", "shop_id", "business_date"),
        CheckConstraint("opening_float_paise >= 0", name="ck_shifts_float"),
        CheckConstraint("counted_cash_paise >= 0", name="ck_shifts_counted"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)  # from the tablet
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT"), index=True
    )
    opened_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # tablet clock
    business_date: Mapped[date] = mapped_column(Date)
    opening_float_paise: Mapped[int] = mapped_column(Integer)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counted_cash_paise: Mapped[int | None] = mapped_column(Integer)
    close_note: Mapped[str] = mapped_column(String(200), default="")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CashMovementKind(enum.StrEnum):
    pay_out = "pay_out"  # paid the milkman, owner took cash to the bank
    pay_in = "pay_in"  # change added to the drawer


class CashMovement(TenantScoped, Base):
    __tablename__ = "cash_movements"
    __table_args__ = (CheckConstraint("amount_paise > 0", name="ck_cash_movements_amount"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)  # from the tablet
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[CashMovementKind] = mapped_column(
        Enum(CashMovementKind, name="cash_movement_kind")
    )
    amount_paise: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(120))
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # tablet clock
