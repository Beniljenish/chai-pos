"""Order events as devices send them (POST /sync/orders), validated per kind."""

import uuid
from typing import Annotated, Any

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.models import OrderEventKind, OrderType

Text = Annotated[str, Field(max_length=200)]
Phone = Annotated[str, Field(max_length=15)]


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


class ModifierSnap(_Strict):
    modifier_id: uuid.UUID
    name: Annotated[str, Field(max_length=40)]
    price_delta_paise: Annotated[int, Field(ge=-100_00, le=100_00)]
    scale_factor: Annotated[str, Field(max_length=12)]
    lines: Annotated[list[dict[str, Any]], Field(max_length=20)] = []


class KotLine(_Strict):
    line_id: uuid.UUID
    menu_item_id: uuid.UUID
    name: Annotated[str, Field(min_length=1, max_length=80)]
    qty: Annotated[int, Field(ge=1, le=999)]
    unit_price_paise: Annotated[int, Field(ge=0, le=10_000_00)]
    gst_rate_bp: Annotated[int, Field(ge=0, le=4000)]
    tax_inclusive: bool
    modifiers: Annotated[list[ModifierSnap], Field(max_length=10)] = []
    note: Text = ""


class OpenData(_Strict):
    order_type: OrderType
    table_id: uuid.UUID | None = None
    covers: Annotated[int, Field(ge=0, le=99)] = 0
    customer_name: Annotated[str, Field(max_length=80)] = ""
    customer_phone: Phone = ""
    message_ok: bool = False
    note: Text = ""


class KotData(_Strict):
    kot_no: Annotated[str, Field(min_length=1, max_length=20)]
    lines: Annotated[list[KotLine], Field(min_length=1, max_length=100)]


class CancelData(_Strict):
    line_id: uuid.UUID
    qty: Annotated[int, Field(ge=1, le=999)]
    reason: Annotated[str, Field(min_length=1, max_length=200)]


class MoveData(_Strict):
    table_id: uuid.UUID | None


class DetailsData(_Strict):
    covers: Annotated[int, Field(ge=0, le=99)] | None = None
    customer_name: Annotated[str, Field(max_length=80)] | None = None
    customer_phone: Phone | None = None
    message_ok: bool | None = None
    note: Text | None = None


class EmptyData(_Strict):
    pass


class ReadyData(_Strict):
    line_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=100)]


class SettleData(_Strict):
    bill_id: uuid.UUID


class CancelOrderData(_Strict):
    reason: Annotated[str, Field(min_length=1, max_length=200)]


DATA = {
    OrderEventKind.open: OpenData,
    OrderEventKind.kot: KotData,
    OrderEventKind.cancel: CancelData,
    OrderEventKind.move: MoveData,
    OrderEventKind.details: DetailsData,
    OrderEventKind.bill_printed: EmptyData,
    OrderEventKind.ready: ReadyData,
    OrderEventKind.settle: SettleData,
    OrderEventKind.cancel_order: CancelOrderData,
}


class OrderEventIn(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    kind: OrderEventKind
    at: AwareDatetime
    by: uuid.UUID | None = None  # who did it, recorded on the device
    data: dict[str, Any] = {}

    @model_validator(mode="after")
    def check_data(self):
        model = DATA[self.kind].model_validate(self.data)
        # Stored as plain JSON (ids as strings); `details` keeps only what was sent.
        self.data = model.model_dump(mode="json", exclude_unset=self.kind == OrderEventKind.details)
        return self


class OrderSyncRequest(BaseModel):
    device_id: uuid.UUID
    events: Annotated[list[OrderEventIn], Field(min_length=1, max_length=200)]


class OrderEventResult(BaseModel):
    id: uuid.UUID
    status: str
    reason: str | None = None


class OrderSyncResponse(BaseModel):
    results: list[OrderEventResult]


# --- areas and tables ---
class AreaIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=40)]
    sort: int = 0


class AreaUpdate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=40)] | None = None
    sort: int | None = None
    is_active: bool | None = None


class TableIn(BaseModel):
    area_id: uuid.UUID
    name: Annotated[str, Field(min_length=1, max_length=20)]
    seats: Annotated[int, Field(ge=1, le=50)] = 4
    sort: int = 0


class TableUpdate(BaseModel):
    area_id: uuid.UUID | None = None
    name: Annotated[str, Field(min_length=1, max_length=20)] | None = None
    seats: Annotated[int, Field(ge=1, le=50)] | None = None
    sort: int | None = None
    is_active: bool | None = None
