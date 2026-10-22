"""What was paid for each ingredient over time (README, "9.21"). Worked out from the stock-in
entries that carried a cost; the "price went up" alert already exists in services/alerts.py."""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ingredient, StockReceipt

# the price is shown per litre, per kilogram or per piece, as people buy it
PER = {"ml": ("litre", Decimal(1000)), "g": ("kg", Decimal(1000)), "piece": ("piece", Decimal(1))}
RECENT = 3  # how many earlier entries the "against your average" figure uses


def _per_unit(r: StockReceipt, factor: Decimal) -> int:
    return int((Decimal(r.cost_paise) * factor / r.base_qty).quantize(Decimal(1), ROUND_HALF_UP))


def _priced(db: Session, ingredient_id: uuid.UUID, limit: int) -> list[StockReceipt]:
    return list(
        db.scalars(
            select(StockReceipt)
            .where(
                StockReceipt.ingredient_id == ingredient_id,
                StockReceipt.cost_paise > 0,
                StockReceipt.base_qty > 0,
            )
            .order_by(StockReceipt.received_at.desc())
            .limit(limit)
        )
    )


def history(db: Session, ing: Ingredient, limit: int = 30) -> dict:
    label, factor = PER[ing.base_unit.value]
    rows = _priced(db, ing.id, limit)
    return {
        "ingredient": ing.name,
        "per": label,
        "entries": [
            {
                "date": r.business_date,
                "supplier": r.supplier,
                "paid_paise": r.cost_paise,
                "price_paise": _per_unit(r, factor),
            }
            for r in rows
        ],
    }


def summary(db: Session) -> list[dict]:
    """Every bought ingredient with a price: the latest, and how it compares with the average of
    the entries before it (null with fewer than two entries)."""
    out = []
    for ing in db.scalars(select(Ingredient).where(Ingredient.is_active).order_by(Ingredient.name)):
        rows = _priced(db, ing.id, RECENT + 1)
        if not rows:
            continue
        label, factor = PER[ing.base_unit.value]
        latest = _per_unit(rows[0], factor)
        earlier = [_per_unit(r, factor) for r in rows[1:]]
        change = None
        if earlier:
            avg = sum(earlier) / len(earlier)
            change = round((latest - avg) * 100 / avg, 1) if avg else None
        out.append(
            {
                "ingredient_id": ing.id,
                "name": ing.name,
                "per": label,
                "latest_paise": latest,
                "change_pct": change,
                "on": rows[0].business_date,
            }
        )
    return out
