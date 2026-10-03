"""Suppliers and purchase orders (README, "Phase 7"). Owner only: buying for the
shop and entering stock are the owner's, like stock-in."""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.common import get_or_404
from app.api.deps import Caller, require_owner
from app.models import Ingredient, PurchaseOrder, Supplier
from app.services import purchases

router = APIRouter(tags=["purchases"])

Qty = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]
Q3 = Decimal("0.001")


class SupplierIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    phone: Annotated[str, Field(max_length=15)] = ""
    note: Annotated[str, Field(max_length=200)] = ""


class SupplierPatch(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    phone: Annotated[str, Field(max_length=15)] | None = None
    note: Annotated[str, Field(max_length=200)] | None = None
    is_active: bool | None = None


class POLineIn(BaseModel):
    ingredient_id: uuid.UUID
    qty: Qty
    expected_cost_paise: Annotated[int, Field(ge=0, le=100_000_00)] = 0


class POIn(BaseModel):
    supplier_id: uuid.UUID
    note: Annotated[str, Field(max_length=200)] = ""
    lines: Annotated[list[POLineIn], Field(min_length=1, max_length=50)]


class ReceivedLineIn(BaseModel):
    line_id: uuid.UUID
    qty: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]
    cost_paise: Annotated[int, Field(ge=0, le=100_000_00)] = 0


class ReceiveIn(BaseModel):
    lines: Annotated[list[ReceivedLineIn], Field(max_length=50)]


def _supplier(s: Supplier) -> dict:
    return {"id": s.id, "name": s.name, "phone": s.phone, "note": s.note, "is_active": s.is_active}


def _q(x: Decimal | None) -> str | None:
    return None if x is None else str(Decimal(x).quantize(Q3))


def _po(db, po: PurchaseOrder) -> dict:
    supplier = db.scalar(select(Supplier).where(Supplier.id == po.supplier_id))
    ids = {ln.ingredient_id for ln in po.lines}
    ingredients = {i.id: i for i in db.scalars(select(Ingredient).where(Ingredient.id.in_(ids)))}
    return {
        "id": po.id,
        "supplier_id": po.supplier_id,
        "supplier_name": supplier.name if supplier else "",
        "status": po.status,
        "note": po.note,
        "created_at": po.created_at,
        "closed_at": po.closed_at,
        "expected_total_paise": sum(ln.expected_cost_paise for ln in po.lines),
        "received_total_paise": sum(ln.cost_paise or 0 for ln in po.lines),
        "lines": [
            {
                "id": ln.id,
                "ingredient_id": ln.ingredient_id,
                "name": ingredients[ln.ingredient_id].name
                if ln.ingredient_id in ingredients
                else "",
                "base_unit": ingredients[ln.ingredient_id].base_unit.value
                if ln.ingredient_id in ingredients
                else "",
                "qty": _q(ln.qty),
                "expected_cost_paise": ln.expected_cost_paise,
                "received_qty": _q(ln.received_qty),
                "cost_paise": ln.cost_paise,
                "receipt_id": ln.receipt_id,
            }
            for ln in po.lines
        ],
    }


def _fail(caller: Caller, e: purchases.PurchaseError):
    caller.db.rollback()
    raise HTTPException(e.status, str(e)) from None


@router.get("/suppliers")
def list_suppliers(caller: Caller = Depends(require_owner)) -> list[dict]:
    rows = caller.db.scalars(select(Supplier).order_by(Supplier.is_active.desc(), Supplier.name))
    return [_supplier(s) for s in rows]


@router.post("/suppliers", status_code=201)
def add_supplier(body: SupplierIn, caller: Caller = Depends(require_owner)) -> dict:
    s = Supplier(name=body.name.strip(), phone=body.phone.strip(), note=body.note.strip())
    caller.db.add(s)
    caller.db.commit()
    return _supplier(s)


@router.patch("/suppliers/{supplier_id}")
def edit_supplier(
    supplier_id: uuid.UUID, body: SupplierPatch, caller: Caller = Depends(require_owner)
) -> dict:
    s = get_or_404(caller.db, Supplier, supplier_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v.strip() if isinstance(v, str) else v)
    caller.db.commit()
    return _supplier(s)


@router.get("/purchase-orders")
def list_orders(caller: Caller = Depends(require_owner)) -> list[dict]:
    rows = caller.db.scalars(
        select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc()).limit(100)
    ).all()
    return [_po(caller.db, po) for po in rows]


@router.get("/purchase-orders/suggest")
def suggest(caller: Caller = Depends(require_owner)) -> dict:
    """What is below its reorder level, and how much to order."""
    return {"lines": purchases.suggest(caller.db)}


@router.post("/purchase-orders", status_code=201)
def create_order(body: POIn, caller: Caller = Depends(require_owner)) -> dict:
    try:
        po = purchases.create_order(
            caller.db,
            body.supplier_id,
            [ln.model_dump() for ln in body.lines],
            body.note.strip(),
            caller.user.id,
        )
    except purchases.PurchaseError as e:
        _fail(caller, e)
    caller.db.commit()
    return _po(caller.db, po)


@router.get("/purchase-orders/{order_id}")
def get_order(order_id: uuid.UUID, caller: Caller = Depends(require_owner)) -> dict:
    return _po(caller.db, get_or_404(caller.db, PurchaseOrder, order_id))


@router.post("/purchase-orders/{order_id}/receive")
def receive(order_id: uuid.UUID, body: ReceiveIn, caller: Caller = Depends(require_owner)) -> dict:
    po = get_or_404(caller.db, PurchaseOrder, order_id)
    try:
        purchases.receive(caller.db, po, [ln.model_dump() for ln in body.lines], caller.user.id)
    except purchases.PurchaseError as e:
        _fail(caller, e)
    caller.db.commit()
    return _po(caller.db, po)


@router.post("/purchase-orders/{order_id}/cancel")
def cancel(order_id: uuid.UUID, caller: Caller = Depends(require_owner)) -> dict:
    po = get_or_404(caller.db, PurchaseOrder, order_id)
    try:
        purchases.cancel(caller.db, po, caller.user.id)
    except purchases.PurchaseError as e:
        _fail(caller, e)
    caller.db.commit()
    return _po(caller.db, po)
