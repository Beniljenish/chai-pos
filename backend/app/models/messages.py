"""Customer messages (README, "Phase 8b"): an outbox, like email.

A row is written in the same transaction as its event (the kitchen marking a
takeaway ready, a settled order's invoice arriving), then delivered after. The
customer's phone number is NOT stored here: it stays on the order, where the
customer gave it, and is read at the moment of sending. The dedupe key makes a
message exactly-once per shop ("ready:<order>", "receipt:<bill>").
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantScoped


class Message(IdMixin, TenantScoped, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("shop_id", "dedupe_key", name="uq_messages_dedupe"),
        CheckConstraint("kind IN ('receipt', 'ready')", name="ck_messages_kind"),
        CheckConstraint(
            "status IN ('pending', 'sent', 'logged', 'failed')", name="ck_messages_status"
        ),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), index=True
    )
    bill_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bills.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(20), default="imessage")
    dedupe_key: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)
    # pending -> sent, or logged (no provider configured: written down, not sent),
    # or failed (gave up after MAX_ATTEMPTS, or the customer withdrew consent).
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(300), default="")
    provider_id: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
