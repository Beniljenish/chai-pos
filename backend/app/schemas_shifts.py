"""Shift and cash-drawer operations, as the tablet sends them (POST /sync/shifts)."""

import uuid
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field

from app.models import CashMovementKind

Paise = Annotated[int, Field(ge=0, le=10_000_000)]  # up to Rs 1,00,000 in a drawer


class ShiftOpenIn(BaseModel):
    op: Literal["open"]
    id: uuid.UUID  # the shift's id, made on the tablet
    at: AwareDatetime
    opening_float_paise: Paise
    cashier_id: uuid.UUID | None = None


class CashMoveIn(BaseModel):
    op: Literal["cash"]
    id: uuid.UUID
    shift_id: uuid.UUID
    at: AwareDatetime
    kind: CashMovementKind
    amount_paise: Annotated[int, Field(ge=1, le=10_000_000)]
    reason: Annotated[str, Field(min_length=1, max_length=120)]
    cashier_id: uuid.UUID | None = None


class ShiftCloseIn(BaseModel):
    op: Literal["close"]
    id: uuid.UUID  # this operation's id
    shift_id: uuid.UUID
    at: AwareDatetime
    counted_cash_paise: Paise
    note: Annotated[str, Field(max_length=200)] = ""
    cashier_id: uuid.UUID | None = None


ShiftOp = Annotated[ShiftOpenIn | CashMoveIn | ShiftCloseIn, Field(discriminator="op")]


class ShiftSyncRequest(BaseModel):
    device_id: uuid.UUID
    ops: Annotated[list[ShiftOp], Field(min_length=1, max_length=100)]


class ShiftOpResult(BaseModel):
    id: uuid.UUID
    status: str  # accepted | duplicate | rejected
    reason: str | None = None


class ShiftSyncResponse(BaseModel):
    results: list[ShiftOpResult]
