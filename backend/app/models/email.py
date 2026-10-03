"""Email outbox: every report is a row first, delivered after.

Written in the same transaction as the event (a bill accepted, a day closed),
so a provider outage never blocks billing and never loses an email. The
dedupe key makes enqueueing idempotent and is sent to the provider as its
idempotency key, so a retry after a crash cannot send twice.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantScoped


class EmailKind(enum.StrEnum):
    bill = "bill"
    day_end = "day_end"
    daily = "daily"
    weekly = "weekly"
    test = "test"


class EmailStatus(enum.StrEnum):
    pending = "pending"
    sent = "sent"
    failed = "failed"  # gave up after MAX_ATTEMPTS


class EmailOutbox(IdMixin, TenantScoped, Base):
    __tablename__ = "email_outbox"
    __table_args__ = (UniqueConstraint("shop_id", "dedupe_key", name="uq_email_outbox_dedupe"),)

    kind: Mapped[EmailKind] = mapped_column(Enum(EmailKind, name="email_kind"))
    dedupe_key: Mapped[str] = mapped_column(String(120))  # "bill:<id>", "daily:2026-10-03"
    to_email: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    html: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    attachments: Mapped[list] = mapped_column(JSONB, default=list)  # [{filename, content}]
    status: Mapped[EmailStatus] = mapped_column(
        Enum(EmailStatus, name="email_status"), default=EmailStatus.pending, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(500), default="")
    provider_id: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
