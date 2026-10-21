"""The super admin: someone who runs food courts and belongs to no shop.

Deliberately NOT a User. A User row always has a shop and a role inside it, and every
shop-level check (tenancy, owner-only routes) is built on that. A super admin lives in
this separate table, signs in at its own endpoint, and gets a token of a different type
that no shop route accepts (and its token is accepted by no shop route either).
"""

import uuid  # noqa: F401  (id comes from IdMixin)
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin


class PlatformAdmin(IdMixin, Base):
    __tablename__ = "platform_admins"

    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(15), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # Wrong-password lockout, the same rule as shop users (services/platform.py).
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
