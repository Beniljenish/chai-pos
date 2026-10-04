"""Request/response shapes for bill sync. Schema errors reject the WHOLE request
(422: the device app is broken); business problems reject one bill with a reason."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

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
    discount: Annotated[int, Field(ge=0, le=10_000_000)] = 0  # Phase 6
    taxable: Paise
    cgst: Paise
    sgst: Paise
    total: Paise


class BillTotalsIn(BaseModel):
    discount: Annotated[int, Field(ge=0, le=10_000_000)] = 0  # Phase 6
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
    gst_rate_bp: Annotated[int, Field(ge=0, le=4000)]
    tax_inclusive: bool
    modifiers: Annotated[list[ModifierSnapshotIn], Field(max_length=10)] = []
    # The cashier's discount on this line (its share of a bill discount is not here).
    discount_paise: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    totals: LineTotalsIn


class PaymentPartIn(BaseModel):
    mode: Literal["cash", "upi", "card", "credit"]
    paise: Annotated[int, Field(ge=1, le=10_000_000)]


class CustomerIn(BaseModel):
    id: uuid.UUID  # made on the tablet; the server keeps one customer per number
    phone: Annotated[str, Field(pattern=r"^\d{10}$")]
    name: Annotated[str, Field(max_length=80)] = ""


class SyncBillIn(BaseModel):
    id: uuid.UUID
    local_seq: Annotated[int, Field(ge=1, le=999_999)]
    invoice_no: Annotated[str, Field(min_length=1, max_length=16)]
    sold_at: AwareDatetime  # must carry a timezone, or "when" is ambiguous
    payment_mode: PaymentMode
    gst_type: GstType
    lines: Annotated[list[BillLineIn], Field(min_length=1, max_length=100)]
    totals: BillTotalsIn
    # Who rang it up, recorded on the tablet at sale time (optional: older apps).
    cashier_id: uuid.UUID | None = None
    # The drawer shift it was rung up in (optional: older apps, shifts switched off).
    shift_id: uuid.UUID | None = None
    # The running order this bill settles (table service), if any.
    order_id: uuid.UUID | None = None
    # Phase 6 (all optional; unused keys are left out of the hash, see bills.py).
    order_part: Annotated[int, Field(ge=1, le=20)] = 1  # split bill: which part
    bill_discount_paise: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    discount_reason: Annotated[str, Field(max_length=200)] = ""
    payment_parts: Annotated[list[PaymentPartIn], Field(min_length=1, max_length=4)] | None = None
    customer: CustomerIn | None = None


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
    discount_paise: int = 0
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
    shift_id: uuid.UUID | None = None
    discount_paise: int = 0
    discount_reason: str = ""
    payment_parts: list | None = None
    customer_id: uuid.UUID | None = None
    order_part: int = 1
    flags: list = []
    order_id: uuid.UUID | None = None
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    round_off_paise: int
    total_paise: int
    totals_mismatch: bool
    server_totals: dict
    lines: list[BillLineOut]
    void: BillVoidOut | None = None
