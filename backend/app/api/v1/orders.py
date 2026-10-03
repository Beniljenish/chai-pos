"""Restaurant service: dining areas and tables (owner), running orders (everyone)."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.common import commit_or_409, get_or_404
from app.api.deps import Caller, get_caller, require_owner
from app.core.time import business_date, utcnow
from app.models import Device, DiningArea, DiningTable, Order, OrderEvent, User
from app.schemas_orders import (
    AreaIn,
    AreaUpdate,
    OrderEventResult,
    OrderSyncRequest,
    OrderSyncResponse,
    TableIn,
    TableUpdate,
)
from app.services import orders

router = APIRouter(tags=["orders"])


# ---------------------------------------------------------------- floor
def floor(db) -> list[dict]:
    """Areas with their tables, in display order (also in the device catalogue)."""
    areas = db.scalars(select(DiningArea).order_by(DiningArea.sort, DiningArea.name)).all()
    tables = db.scalars(select(DiningTable).order_by(DiningTable.sort, DiningTable.name)).all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "sort": a.sort,
            "is_active": a.is_active,
            "tables": [
                {
                    "id": t.id,
                    "name": t.name,
                    "seats": t.seats,
                    "sort": t.sort,
                    "is_active": t.is_active,
                }
                for t in tables
                if t.area_id == a.id
            ],
        }
        for a in areas
    ]


@router.get("/dining")
def get_floor(caller: Caller = Depends(get_caller)) -> list[dict]:
    return floor(caller.db)


@router.post("/areas", status_code=201)
def create_area(body: AreaIn, caller: Caller = Depends(require_owner)) -> dict:
    a = DiningArea(name=body.name.strip(), sort=body.sort)
    caller.db.add(a)
    commit_or_409(caller.db, "An area with that name already exists")
    return {"id": a.id, "name": a.name, "sort": a.sort, "is_active": a.is_active}


@router.patch("/areas/{area_id}")
def update_area(
    area_id: uuid.UUID, body: AreaUpdate, caller: Caller = Depends(require_owner)
) -> dict:
    a = get_or_404(caller.db, DiningArea, area_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a, k, v.strip() if isinstance(v, str) else v)
    commit_or_409(caller.db, "An area with that name already exists")
    return {"id": a.id, "name": a.name, "sort": a.sort, "is_active": a.is_active}


def _table_out(t: DiningTable) -> dict:
    return {
        "id": t.id,
        "area_id": t.area_id,
        "name": t.name,
        "seats": t.seats,
        "sort": t.sort,
        "is_active": t.is_active,
    }


@router.post("/tables", status_code=201)
def create_table(body: TableIn, caller: Caller = Depends(require_owner)) -> dict:
    get_or_404(caller.db, DiningArea, body.area_id)  # the area must be this shop's
    t = DiningTable(area_id=body.area_id, name=body.name.strip(), seats=body.seats, sort=body.sort)
    caller.db.add(t)
    commit_or_409(caller.db, "A table with that name already exists")
    return _table_out(t)


@router.patch("/tables/{table_id}")
def update_table(
    table_id: uuid.UUID, body: TableUpdate, caller: Caller = Depends(require_owner)
) -> dict:
    t = get_or_404(caller.db, DiningTable, table_id)
    data = body.model_dump(exclude_unset=True)
    if "area_id" in data:
        get_or_404(caller.db, DiningArea, data["area_id"])
    for k, v in data.items():
        setattr(t, k, v.strip() if isinstance(v, str) else v)
    commit_or_409(caller.db, "A table with that name already exists")
    return _table_out(t)


# ---------------------------------------------------------------- orders
@router.post("/sync/orders", response_model=OrderSyncResponse)
def sync_orders(body: OrderSyncRequest, caller: Caller = Depends(get_caller)):
    """Order events made on a device (offline too). Always 200 with a result per
    event, like bills: accepted / duplicate / rejected with a reason."""
    device = get_or_404(caller.db, Device, body.device_id)
    if not device.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This device has been deactivated")
    ctx = orders.OrderContext(
        db=caller.db,
        device=device,
        caller_id=caller.user.id,
        staff_ids=frozenset(caller.db.scalars(select(User.id))),
    )
    results = orders.ingest(ctx, [e.model_dump() for e in body.events])
    return OrderSyncResponse(
        results=[OrderEventResult(id=i, status=s, reason=r) for i, s, r in results]
    )


def _order_out(o: Order) -> dict:
    return {
        "id": o.id,
        "device_id": o.device_id,
        "order_type": o.order_type.value,
        "status": o.status.value,
        "table_id": o.table_id,
        "opened_at": o.opened_at,
        "business_date": o.business_date,
        "updated_at": o.updated_at,
        "state": o.state,
    }


@router.get("/orders/live")
def live_orders(
    since: datetime | None = Query(default=None),
    caller: Caller = Depends(get_caller),
) -> dict:
    """What every device shows: open and billed orders, and anything changed since
    the device's last look. `server_time` is the next `since`."""
    now = utcnow()
    rows = orders.live(caller.db, since)
    # Events of unfinished orders: a device adds its own unsent ones and applies
    # the same rules, so what it shows never waits for the server.
    open_ids = [o.id for o in rows if o.status.value in ("open", "billed")]
    events: dict = {oid: [] for oid in open_ids}
    if open_ids:
        for e in caller.db.scalars(
            select(OrderEvent).where(OrderEvent.order_id.in_(open_ids)).order_by(OrderEvent.at)
        ):
            events[e.order_id].append(
                {
                    "id": e.id,
                    "order_id": e.order_id,
                    "kind": e.kind.value,
                    "at": e.at,
                    "by": e.by,
                    "data": e.data,
                }
            )
    return {
        "server_time": now,
        "orders": [{**_order_out(o), "events": events.get(o.id)} for o in rows],
    }


@router.get("/reports/service", tags=["reports"])
def service(
    day: date | None = Query(default=None, alias="business_date"),
    caller: Caller = Depends(require_owner),
) -> dict:
    """Owner: cancelled items, bills changed after printing, cancelled and unfinished orders."""
    return orders.service_report(caller.db, day or business_date())


@router.get("/orders/{order_id}")
def get_order(order_id: uuid.UUID, caller: Caller = Depends(require_owner)) -> dict:
    """Owner: an order with its full history (who added, cancelled, moved what)."""
    o = get_or_404(caller.db, Order, order_id)
    evs = caller.db.scalars(
        select(OrderEvent).where(OrderEvent.order_id == o.id).order_by(OrderEvent.at, OrderEvent.id)
    ).all()
    names = dict(caller.db.execute(select(User.id, User.name)).all())
    return {
        **_order_out(o),
        "events": [
            {
                "id": e.id,
                "kind": e.kind.value,
                "at": e.at,
                "by_name": names.get(e.by, ""),
                "data": e.data,
            }
            for e in evs
        ],
    }
