"""Suppliers and purchase orders (README, "Phase 7").

Receiving an order makes ordinary stock-in receipts (services/stock.stock_in),
so stock moves only through the ledger, and the latest purchase price updates
the same way it does for a stock-in typed by hand.
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models import Ingredient, IngredientKind, PurchaseOrder, PurchaseOrderLine, Supplier
from app.services import stock

Q3 = Decimal("0.001")


class PurchaseError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def create_order(
    db: Session, supplier_id: uuid.UUID, lines: list[dict], note: str, user_id: uuid.UUID
) -> PurchaseOrder:
    supplier = db.scalar(select(Supplier).where(Supplier.id == supplier_id))  # tenant-scoped
    if supplier is None:
        raise PurchaseError("Unknown supplier", 404)
    ids = {ln["ingredient_id"] for ln in lines}
    found = {i.id: i for i in db.scalars(select(Ingredient).where(Ingredient.id.in_(ids)))}
    if len(found) != len(ids):
        raise PurchaseError("Unknown ingredient", 404)
    if any(i.kind != IngredientKind.raw for i in found.values()):
        raise PurchaseError("Batch items are made here, not bought")
    po = PurchaseOrder(supplier_id=supplier.id, status="open", note=note, created_by=user_id)
    po.lines = [
        PurchaseOrderLine(
            position=n,
            ingredient_id=ln["ingredient_id"],
            qty=ln["qty"],
            expected_cost_paise=ln.get("expected_cost_paise", 0),
        )
        for n, ln in enumerate(lines, start=1)
    ]
    db.add(po)
    db.flush()
    return po


def receive(db: Session, po: PurchaseOrder, got: list[dict], user_id: uuid.UUID) -> PurchaseOrder:
    """What came, line by line (a line not mentioned, or 0, did not come)."""
    if po.status != "open":
        raise PurchaseError(f"This order is already {po.status}", 409)
    supplier = db.scalar(select(Supplier).where(Supplier.id == po.supplier_id))
    by_line = {g["line_id"]: g for g in got}
    for line in po.lines:
        g = by_line.get(line.id, {})
        qty = Decimal(g.get("qty", 0))
        cost = int(g.get("cost_paise", 0))
        line.received_qty, line.cost_paise = qty, cost
        if qty > 0:
            ingredient = db.scalar(select(Ingredient).where(Ingredient.id == line.ingredient_id))
            receipt = stock.stock_in(
                db,
                ingredient=ingredient,
                packs=[],
                loose_qty=qty,
                cost_paise=cost,
                supplier=supplier.name if supplier else "",
                expiry_date=None,
                confirm_large=True,  # the owner ordered this amount on purpose
                user_id=user_id,
            )
            line.receipt_id = receipt.id
    po.status, po.closed_by, po.closed_at = "received", user_id, utcnow()
    db.flush()
    return po


def cancel(db: Session, po: PurchaseOrder, user_id: uuid.UUID) -> PurchaseOrder:
    if po.status != "open":
        raise PurchaseError(f"This order is already {po.status}", 409)
    po.status, po.closed_by, po.closed_at = "cancelled", user_id, utcnow()
    db.flush()
    return po


def suggest(db: Session) -> list[dict]:
    """Bought items below their reorder level, with enough to bring each up to
    twice that level: simple, predictable, and the owner edits it before sending."""
    out = []
    for r in stock.stock_on_hand(db):
        i = r.ingredient
        if not i.is_active or i.kind != IngredientKind.raw or i.reorder_level is None:
            continue
        if r.qty >= i.reorder_level:
            continue
        qty = (i.reorder_level * 2 - max(r.qty, Decimal(0))).quantize(Q3)
        cost = (qty * Decimal(i.cost_per_unit_paise or 0)).quantize(Decimal(1), ROUND_HALF_UP)
        out.append(
            {
                "ingredient_id": i.id,
                "name": i.name,
                "base_unit": i.base_unit.value,
                "on_hand": str(r.qty.quantize(Q3)),
                "reorder_level": str(Decimal(i.reorder_level).quantize(Q3)),
                "qty": str(qty),
                "expected_cost_paise": int(cost),
            }
        )
    return out
