"""Request/response shapes for bill sync. Schema errors reject the WHOLE request
(422: the device app is broken); business problems reject one bill with a reason."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models import GstType, PaymentMode, VoidReason

Paise = Annotated[int, Field(ge=-10_000_000, le=10_000_000)]


class ModifierSnapshotLineIn(BaseModel):
    ingredient_id: uuid.UUID
    qty_delta: Annotated[Decimal, Field(max_digits=14, decimal_places=3)]


class ModifierSnapshotIn(BaseModel):
    modifier_id: uuid.UUID
    name: Annotated[str, Field(min_length=1, max_length=40)]
    price_delta_paise: Paise
    scale_factor: Annotated[Decimal, Field(gt=0, le=10, max_digits=6, decimal_places=3)]
    lines: Annotated[list[ModifierSnapshotLineIn], Field(max_length=20)] = []


class LineTotalsIn(BaseModel):
    gross: Paise
    taxable: Paise
    cgst: Paise
    sgst: Paise
    total: Paise


class BillTotalsIn(BaseModel):
    taxable: Paise
    cgst: Paise
    sgst: Paise
    subtotal: Paise
    round_off: Annotated[int, Field(ge=-50, le=50)]
    total: Annotated[int, Field(ge=0, le=10_000_000)]


class BillLineIn(BaseModel):
    menu_item_id: uuid.UUID
    recipe_id: uuid.UUID | None
    name: Annotated[str, Field(min_length=1, max_length=80)]
    unit_price_paise: Paise
    qty: Annotated[int, Field(ge=1, le=999)]
    gst_rate_bp: Annotated[int, Field(ge=0, le=2800)]
    tax_inclusive: bool
    modifiers: Annotated[list[ModifierSnapshotIn], Field(max_length=10)] = []
    totals: LineTotalsIn


class SyncBillIn(BaseModel):
    id: uuid.UUID
    local_seq: Annotated[int, Field(ge=1, le=999_999)]
    invoice_no: Annotated[str, Field(min_length=1, max_length=16)]
    sold_at: AwareDatetime  # must carry a timezone, or "when" is ambiguous
    payment_mode: PaymentMode
    gst_type: GstType
    lines: Annotated[list[BillLineIn], Field(min_length=1, max_length=100)]
    totals: BillTotalsIn


class SyncRequest(BaseModel):
    device_id: uuid.UUID
    bills: Annotated[list[SyncBillIn], Field(min_length=1, max_length=50)]


class SyncResultOut(BaseModel):
    id: uuid.UUID
    status: str
    invoice_no: str | None
    totals_mismatch: bool
    reason: str | None


class SyncResponse(BaseModel):
    results: list[SyncResultOut]


# --- reading bills back ---
class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BillLineModifierOut(ORM):
    modifier_id: uuid.UUID
    name_snapshot: str
    price_delta_paise: int


class BillLineOut(ORM):
    position: int
    menu_item_id: uuid.UUID
    recipe_id: uuid.UUID | None
    name_snapshot: str
    unit_price_paise: int
    qty: int
    gst_rate_bp: int
    tax_inclusive: bool
    total_paise: int
    modifiers: list[BillLineModifierOut]


class BillVoidOut(ORM):
    reason: VoidReason
    note: str
    stock_returned: bool
    voided_by_name: str
    voided_at: datetime


class VoidIn(BaseModel):
    reason: VoidReason
    note: Annotated[str, Field(max_length=200)] = ""
    drink_was_made: bool = False


class BillOut(ORM):
    id: uuid.UUID
    invoice_no: str
    device_id: uuid.UUID
    cashier_id: uuid.UUID
    sold_at: datetime
    received_at: datetime
    business_date: date
    payment_mode: PaymentMode
    status: str
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    round_off_paise: int
    total_paise: int
    totals_mismatch: bool
    server_totals: dict
    lines: list[BillLineOut]
    void: BillVoidOut | None = None
