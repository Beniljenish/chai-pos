"""A customer's account for ordering at food courts.

Deliberately NOT a User and NOT the khata `Customer` (that one is one shop's list of
people who owe it money). A customer account belongs to no shop: one login works at
every outlet of every food court. Its token has its own type, so no shop route or
admin route accepts it, and none of theirs is accepted by the customer routes.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin


class CustomerAccount(IdMixin, Base):
    __tablename__ = "customer_accounts"

    name: Mapped[str] = mapped_column(String(40))
    phone: Mapped[str] = mapped_column(String(15), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # Set when the super admin resets a forgotten password: the customer must choose their own.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # Bumped on every password change or reset; a token carries the value it was issued under,
    # so changing the password logs the account out everywhere.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # When the number was proved by a code sent to it (null: never, or verification was off).
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
