"""What each menu item costs to make and what it keeps (README, "9.10").

Cost is the item's current recipe times the latest price paid for each
ingredient (`Ingredient.cost_per_unit_paise`, set on every stock-in). A made-here
ingredient (a decoction) costs what its own recipe's inputs cost, spread over the
batch's yield. Size and add-on options are not included: this is the standard
serving.

An item with an ingredient that has no price yet gets no margin at all: showing
"100% kept" because milk's price was never entered would be a lie. It is listed
as incomplete with the names to fix.

Money is integer paise; unit costs are exact decimals and round half up once, at
the end, to a whole paisa.
"""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import business_date, utcnow
from app.models import Bill, BillLine, BillStatus, Ingredient, IngredientKind, MenuItem, Shop
from app.services import gst
from app.services.recipes import resolve_recipe

ZERO = Decimal(0)
MAX_DEPTH = 4  # a decoction made from a decoction made from ...: stop, never loop


def _paise(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


class _Costs:
    """Unit costs (paise per base unit) with made-here ingredients worked out."""

    def __init__(self, db: Session):
        self.db = db
        self.by_id = {i.id: i for i in db.scalars(select(Ingredient))}
        self._cache: dict = {}

    def unit(self, ingredient_id, depth: int = 0) -> Decimal | None:
        """Paise per base unit, or None when no price is known."""
        if ingredient_id in self._cache:
            return self._cache[ingredient_id]
        ing = self.by_id[ingredient_id]
        cost: Decimal | None = Decimal(ing.cost_per_unit_paise or 0) or None
        if ing.kind == IngredientKind.prep and depth < MAX_DEPTH:
            recipe = resolve_recipe(self.db, prep_ingredient_id=ing.id)
            if recipe and recipe.yield_qty and recipe.yield_qty > 0:
                total, ok = ZERO, True
                for ln in recipe.lines:
                    u = self.unit(ln.ingredient_id, depth + 1)
                    if u is None:
                        ok = False
                        break
                    total += ln.qty * u
                cost = total / recipe.yield_qty if ok else cost
        self._cache[ingredient_id] = cost
        return cost

    def missing_in(self, ingredient_id, depth: int = 0) -> list[str]:
        """Names of the ingredients with no price that this one depends on."""
        if self.unit(ingredient_id, depth) is not None:
            return []
        ing = self.by_id[ingredient_id]
        if ing.kind == IngredientKind.prep and depth < MAX_DEPTH:
            recipe = resolve_recipe(self.db, prep_ingredient_id=ing.id)
            if recipe and recipe.lines:
                names = [
                    n for ln in recipe.lines for n in self.missing_in(ln.ingredient_id, depth + 1)
                ]
                if names:
                    return names
        return [ing.name]


def margin_report(db: Session) -> dict:
    shop = db.scalar(select(Shop))
    costs = _Costs(db)
    since = business_date(utcnow()) - timedelta(days=28)
    sold = dict(
        db.execute(
            select(BillLine.menu_item_id, func.sum(BillLine.qty))
            .join(Bill, Bill.id == BillLine.bill_id)
            .where(Bill.status != BillStatus.void, Bill.business_date >= since)
            .group_by(BillLine.menu_item_id)
        ).all()
    )
    rows = []
    for item in db.scalars(select(MenuItem).where(MenuItem.is_active).order_by(MenuItem.name)):
        recipe = resolve_recipe(db, menu_item_id=item.id)
        totals = gst.compute_bill(
            [gst.LineIn(item.price_paise, 1, item.gst_rate_bp, item.tax_inclusive)], shop.gst_type
        )
        net = totals.taxable
        row = {
            "menu_item_id": item.id,
            "name": item.name,
            "category": item.category,
            "price_paise": item.price_paise,
            "net_paise": net,
            "sold_28d": int(sold.get(item.id, 0)),
            "cost_paise": None,
            "margin_paise": None,
            "margin_pct": None,
            "status": "ok",
            "missing": [],
        }
        if recipe is None or not recipe.lines:
            row["status"], row["missing"] = "no_recipe", []
        else:
            missing = [n for ln in recipe.lines for n in costs.missing_in(ln.ingredient_id)]
            if missing:
                row["status"], row["missing"] = "incomplete", sorted(set(missing))
            else:
                cost = _paise(
                    sum((ln.qty * costs.unit(ln.ingredient_id) for ln in recipe.lines), ZERO)
                )
                row["cost_paise"] = cost
                row["margin_paise"] = net - cost
                if net > 0:
                    row["margin_pct"] = int(
                        (Decimal(net - cost) * 100 / Decimal(net)).quantize(
                            Decimal(1), rounding=ROUND_HALF_UP
                        )
                    )
        rows.append(row)
    # Worst margin first; items we cannot cost go last, so they are not mistaken for the worst.
    rows.sort(key=lambda r: (r["margin_pct"] is None, r["margin_pct"] or 0, r["name"].lower()))
    return {"items": rows}
