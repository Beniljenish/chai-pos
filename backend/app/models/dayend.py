"""Phase 3: wastage and the blind day-end count.

Variance is only meaningful if every known loss has a reason (wastage) and the
count is honest (blind: whoever counts never sees what the system expects).
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TenantScoped
from app.models.catalogue import QTY


def _fk(target: str, ondelete: str = "RESTRICT"):
    return ForeignKey(target, ondelete=ondelete)


class WastageReason(enum.StrEnum):
    spoiled = "spoiled"  # milk curdled, fruit gone soft
    spilled = "spilled"  # glass dropped
    remake = "remake"  # tea remade after a complaint
    prep_loss = "prep_loss"  # leftover decoction thrown at close
    staff = "staff"  # staff tea
    complimentary = "complimentary"  # owner only
    theft = "theft"  # owner only, after investigation


OWNER_ONLY_REASONS = frozenset({WastageReason.complimentary, WastageReason.theft})


class WastageStatus(enum.StrEnum):
    approved = "approved"  # counts as a known loss (owner entries, small ones, or decided)
    pending = "pending"  # a cashier's large entry, waiting for the owner
    rejected = "rejected"  # the owner did not accept it: reversed, so it shows as missing


class WastageEntry(IdMixin, TenantScoped, Base):
    """One loss with a reason. Exactly one of ingredient / menu item: a dropped
    juice deducts its whole recipe; spoiled milk deducts milk."""

    __tablename__ = "wastage_entries"
    __table_args__ = (
        CheckConstraint(
            "(ingredient_id IS NULL) <> (menu_item_id IS NULL)", name="ck_wastage_one_target"
        ),
        CheckConstraint("qty > 0", name="ck_wastage_positive"),
    )

    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), _fk("ingredients.id")
    )
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), _fk("menu_items.id"))
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), _fk("recipes.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)  # base units, or servings for a menu item
    reason: Mapped[WastageReason] = mapped_column(Enum(WastageReason, name="wastage_reason"))
    note: Mapped[str] = mapped_column(String(200), default="")
    value_paise: Mapped[int] = mapped_column(Integer, default=0)  # at cost, when recorded
    business_date: Mapped[date] = mapped_column(Date, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[WastageStatus] = mapped_column(
        Enum(WastageStatus, name="wastage_status"),
        default=WastageStatus.approved,
        server_default=WastageStatus.approved.value,
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), _fk("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DayCountStatus(enum.StrEnum):
    counting = "counting"  # being counted (or waiting for a recount)
    submitted = "submitted"  # counted; waiting for the owner
    approved = "approved"  # owner approved: counted stock is the new truth, day locked


class DayCount(IdMixin, TenantScoped, Base):
    __tablename__ = "day_counts"
    __table_args__ = (UniqueConstraint("shop_id", "business_date", name="uq_day_counts_date"),)

    business_date: Mapped[date] = mapped_column(Date)
    status: Mapped[DayCountStatus] = mapped_column(
        Enum(DayCountStatus, name="day_count_status"), default=DayCountStatus.counting
    )
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), _fk("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), _fk("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["DayCountLine"]] = relationship(
        back_populates="day_count", cascade="all, delete-orphan"
    )


class DayCountLine(IdMixin, TenantScoped, Base):
    """One counted ingredient. The expected/variance columns are frozen at approval,
    so the report for a closed day never shifts."""

    __tablename__ = "day_count_lines"
    __table_args__ = (
        UniqueConstraint("day_count_id", "ingredient_id", name="uq_day_count_lines_ingredient"),
        CheckConstraint("counted_qty >= 0", name="ck_day_count_lines_counted"),
    )

    day_count_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("day_counts.id", "CASCADE"), index=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("ingredients.id"))
    entered: Mapped[list] = mapped_column(JSONB)
    loose_qty: Mapped[Decimal] = mapped_column(QTY, default=Decimal(0))
    counted_qty: Mapped[Decimal] = mapped_column(QTY)
    recount_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    recounted: Mapped[bool] = mapped_column(Boolean, default=False)
    counted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users.id"))
    counted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Frozen at approval:
    expected_qty: Mapped[Decimal | None] = mapped_column(QTY)
    cost_per_unit_paise: Mapped[Decimal | None] = mapped_column(QTY)
    variance_paise: Mapped[int | None] = mapped_column(Integer)

    day_count: Mapped[DayCount] = relationship(back_populates="lines")


class HandoverCount(IdMixin, TenantScoped, Base):
    """A blind count of the 'count every shift' items (milk, fruit) when one
    shift hands over to the next. It changes no stock: the day-end count stays
    the truth. It pins the day's gap to the hours it happened in."""

    __tablename__ = "handover_counts"

    business_date: Mapped[date] = mapped_column(Date, index=True)
    counted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # server clock
    counted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users.id"))
    # The shift being closed, when there is one. No foreign key: the tablet may
    # not have sent the shift yet (it syncs later, offline-first).
    shift_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    lines: Mapped[list["HandoverCountLine"]] = relationship(
        back_populates="handover", cascade="all, delete-orphan"
    )


class HandoverCountLine(IdMixin, TenantScoped, Base):
    __tablename__ = "handover_count_lines"
    __table_args__ = (
        UniqueConstraint("handover_id", "ingredient_id", name="uq_handover_count_lines_ingredient"),
        CheckConstraint("counted_qty >= 0", name="ck_handover_count_lines_counted"),
    )

    handover_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("handover_counts.id", "CASCADE"), index=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("ingredients.id"))
    entered: Mapped[list] = mapped_column(JSONB)
    loose_qty: Mapped[Decimal] = mapped_column(QTY, default=Decimal(0))
    counted_qty: Mapped[Decimal] = mapped_column(QTY)

    handover: Mapped[HandoverCount] = relationship(back_populates="lines")
