"""Every change to stock is a row in the append-only ledger.
Stock on hand = SUM(qty_delta). There is no stored balance to drift."""

import statistics
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import business_date, utcnow
from app.models import (
    Ingredient,
    IngredientKind,
    LedgerReason,
    PackUnit,
    PrepBatch,
    StockLedger,
    StockReceipt,
)
from app.services.recipes import Q3, resolve_recipe

LARGE_RECEIPT_FACTOR = 3
LARGE_RECEIPT_MIN_HISTORY = 3  # need a few receipts before "unusually large" means anything


class StockError(ValueError):
    pass


class LargeReceiptNeedsConfirmation(StockError):
    def __init__(self, base_qty: Decimal, typical: Decimal):
        self.base_qty, self.typical = base_qty, typical
        super().__init__(
            f"{base_qty} is more than {LARGE_RECEIPT_FACTOR}x the usual stock-in ({typical}). "
            "Resend with confirm_large=true if this is correct."
        )


@dataclass(frozen=True)
class PackQty:
    pack_unit_id: uuid.UUID
    qty: Decimal


def _ledger(db, *, ingredient_id, delta, reason, ref_type, ref_id, user_id, bdate) -> None:
    db.add(
        StockLedger(
            ingredient_id=ingredient_id,
            qty_delta=delta,
            reason=reason,
            ref_type=ref_type,
            ref_id=ref_id,
            business_date=bdate,
            created_by=user_id,
        )
    )


def stock_in(
    db: Session,
    *,
    ingredient: Ingredient,
    packs: list[PackQty],
    loose_qty: Decimal,
    cost_paise: int,
    supplier: str,
    expiry_date: date | None,
    confirm_large: bool,
    user_id: uuid.UUID,
) -> StockReceipt:
    if ingredient.kind != IngredientKind.raw:
        raise StockError("Prep items are made with a prep batch, not received as stock-in")

    units = {
        u.id: u
        for u in db.scalars(
            select(PackUnit).where(PackUnit.id.in_([p.pack_unit_id for p in packs]))
        )
    }
    entered, total = [], Decimal(0)
    for p in packs:
        unit = units.get(p.pack_unit_id)
        if unit is None or unit.ingredient_id != ingredient.id:
            raise StockError(f"Pack unit {p.pack_unit_id} does not belong to {ingredient.name}")
        total += p.qty * unit.qty_in_base
        entered.append(
            {
                "pack_unit_id": str(unit.id),
                "name": unit.name,
                "qty": str(p.qty),
                "qty_in_base": str(unit.qty_in_base),
            }
        )
    total = (total + loose_qty).quantize(Q3)
    if total <= 0:
        raise StockError("Stock-in quantity must be more than zero")

    typical = _typical_receipt(db, ingredient.id)
    if typical is not None and total > typical * LARGE_RECEIPT_FACTOR and not confirm_large:
        raise LargeReceiptNeedsConfirmation(total, typical)

    now = utcnow()
    receipt = StockReceipt(
        ingredient_id=ingredient.id,
        supplier=supplier,
        entered=entered,
        loose_qty=loose_qty,
        base_qty=total,
        cost_paise=cost_paise,
        expiry_date=expiry_date,
        business_date=business_date(now),
        received_by=user_id,
        received_at=now,
    )
    db.add(receipt)
    db.flush()
    _ledger(
        db,
        ingredient_id=ingredient.id,
        delta=total,
        reason=LedgerReason.stock_in,
        ref_type="stock_receipt",
        ref_id=receipt.id,
        user_id=user_id,
        bdate=receipt.business_date,
    )
    if cost_paise > 0:
        # Latest purchase price per base unit; feeds variance in rupees later.
        ingredient.cost_per_unit_paise = (Decimal(cost_paise) / total).quantize(Decimal("0.0001"))
    return receipt


def _typical_receipt(db: Session, ingredient_id: uuid.UUID) -> Decimal | None:
    recent = db.scalars(
        select(StockReceipt.base_qty)
        .where(StockReceipt.ingredient_id == ingredient_id)
        .order_by(StockReceipt.received_at.desc())
        .limit(10)
    ).all()
    if len(recent) < LARGE_RECEIPT_MIN_HISTORY:
        return None
    return Decimal(statistics.median(recent))


def make_prep_batch(
    db: Session, *, prep: Ingredient, batches: Decimal, user_id: uuid.UUID
) -> PrepBatch:
    if prep.kind != IngredientKind.prep:
        raise StockError(f"{prep.name} is not a prep item")
    recipe = resolve_recipe(db, prep_ingredient_id=prep.id)
    if recipe is None:
        raise StockError(f"{prep.name} has no batch recipe yet")

    now = utcnow()
    batch = PrepBatch(
        recipe_id=recipe.id,
        batches=batches,
        business_date=business_date(now),
        made_by=user_id,
        made_at=now,
    )
    db.add(batch)
    db.flush()
    common = {
        "ref_type": "prep_batch",
        "ref_id": batch.id,
        "user_id": user_id,
        "bdate": batch.business_date,
    }
    for line in recipe.lines:
        _ledger(
            db,
            ingredient_id=line.ingredient_id,
            reason=LedgerReason.prep_out,
            delta=-(line.qty * batches).quantize(Q3),
            **common,
        )
    _ledger(
        db,
        ingredient_id=prep.id,
        reason=LedgerReason.prep_in,
        delta=(recipe.yield_qty * batches).quantize(Q3),
        **common,
    )
    return batch


@dataclass(frozen=True)
class OnHand:
    ingredient: Ingredient
    qty: Decimal


def stock_on_hand(db: Session) -> list[OnHand]:
    """Negative stock is allowed and shown, not blocked: a late stock-in entry
    must never stop billing at the counter. Negative = a data problem to fix."""
    totals = dict(
        db.execute(
            select(StockLedger.ingredient_id, func.sum(StockLedger.qty_delta)).group_by(
                StockLedger.ingredient_id
            )
        ).all()
    )
    items = db.scalars(select(Ingredient).order_by(Ingredient.kind, Ingredient.name)).all()
    return [OnHand(i, Decimal(totals.get(i.id) or 0)) for i in items]
