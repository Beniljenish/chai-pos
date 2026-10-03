import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.common import commit_or_409, get_or_404, unprocessable
from app.api.deps import Caller, get_caller, require_owner
from app.models import Ingredient, StockLedger
from app.schemas_catalogue import (
    LedgerOut,
    OpeningIn,
    OpeningOut,
    PrepBatchIn,
    PrepBatchOut,
    StockInIn,
    StockOut,
    StockReceiptOut,
)
from app.services import stock as stock_service

router = APIRouter(tags=["stock"])


@router.post("/stock-in", response_model=StockReceiptOut, status_code=201)
def stock_in(body: StockInIn, caller: Caller = Depends(require_owner)):
    ingredient = get_or_404(caller.db, Ingredient, body.ingredient_id)
    try:
        receipt = stock_service.stock_in(
            caller.db,
            ingredient=ingredient,
            packs=[stock_service.PackQty(p.pack_unit_id, p.qty) for p in body.packs],
            loose_qty=body.loose_qty,
            cost_paise=body.cost_paise,
            supplier=body.supplier,
            expiry_date=body.expiry_date,
            confirm_large=body.confirm_large,
            user_id=caller.user.id,
        )
    except stock_service.LargeReceiptNeedsConfirmation as e:
        caller.db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": str(e),
                "base_qty": str(e.base_qty),
                "typical": str(e.typical),
                "needs": "confirm_large",
            },
        ) from None
    except stock_service.StockError as e:
        caller.db.rollback()
        raise unprocessable(str(e)) from None
    caller.db.commit()
    return receipt


@router.post("/stock/opening", response_model=OpeningOut, status_code=201)
def set_opening(body: OpeningIn, caller: Caller = Depends(require_owner)):
    ingredient = get_or_404(caller.db, Ingredient, body.ingredient_id)
    try:
        opening = stock_service.set_opening(
            caller.db,
            ingredient=ingredient,
            packs=[stock_service.PackQty(p.pack_unit_id, p.qty) for p in body.packs],
            loose_qty=body.loose_qty,
            user_id=caller.user.id,
        )
    except stock_service.OpeningAlreadySet as e:
        caller.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    except stock_service.StockError as e:
        caller.db.rollback()
        raise unprocessable(str(e)) from None
    commit_or_409(caller.db, "Opening stock for this ingredient was already entered")
    return opening


@router.post("/prep-batches", response_model=PrepBatchOut, status_code=201)
def make_prep_batch(body: PrepBatchIn, caller: Caller = Depends(get_caller)):
    # Cashiers make the decoction, so they log batches too.
    prep = get_or_404(caller.db, Ingredient, body.ingredient_id)
    try:
        batch = stock_service.make_prep_batch(
            caller.db, prep=prep, batches=body.batches, user_id=caller.user.id
        )
    except stock_service.StockError as e:
        caller.db.rollback()
        raise unprocessable(str(e)) from None
    caller.db.commit()
    return batch


@router.get("/stock", response_model=list[StockOut])
def stock_on_hand(caller: Caller = Depends(require_owner)):
    # Owner only for now: Phase 3's blind counts must not let cashiers see
    # expected quantities before counting.
    return [
        StockOut(
            ingredient_id=s.ingredient.id,
            name=s.ingredient.name,
            kind=s.ingredient.kind,
            base_unit=s.ingredient.base_unit,
            on_hand=s.qty,
            is_negative=s.qty < 0,
            below_reorder=s.ingredient.reorder_level is not None
            and s.qty < s.ingredient.reorder_level,
            has_opening=s.has_opening,
            is_active=s.ingredient.is_active,
        )
        for s in stock_service.stock_on_hand(caller.db)
    ]


@router.get("/stock/{ingredient_id}/ledger", response_model=list[LedgerOut])
def ledger_history(
    ingredient_id: uuid.UUID, limit: int = 200, caller: Caller = Depends(require_owner)
):
    ingredient = get_or_404(caller.db, Ingredient, ingredient_id)
    return caller.db.scalars(
        select(StockLedger)
        .where(StockLedger.ingredient_id == ingredient.id)
        .order_by(StockLedger.created_at.desc())
        .limit(min(max(limit, 1), 1000))
    ).all()
