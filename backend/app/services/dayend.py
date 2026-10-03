"""Wastage, the blind day-end count, and variance.

    expected closing = opening + stock-in + batches made - batches used
                       - sales (by recipe version, with modifiers) - wastage
    variance         = counted - expected        (negative = stock missing)
    adherence %      = expected usage / actual usage x 100

Everything is read from the append-only ledger, filtered by business date and
reason, so every number in the report can be traced to the rows behind it.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.time import business_date as business_date_of
from app.core.time import utcnow
from app.models import (
    OWNER_ONLY_REASONS,
    DayCount,
    DayCountLine,
    DayCountStatus,
    Ingredient,
    IngredientKind,
    LedgerReason,
    MenuItem,
    StockLedger,
    WastageEntry,
    WastageReason,
)
from app.services.billing import consumption_for_line
from app.services.recipes import Q3, resolve_recipe
from app.services.stock import PackQty, StockError, _convert_packs, physically_counted

ZERO = Decimal(0)


class DayEndError(ValueError):
    pass


class DayLocked(DayEndError):
    pass


def _paise(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- costs
def unit_costs(db: Session, ingredients: list[Ingredient]) -> dict[uuid.UUID, Decimal]:
    """Paise per base unit. Bought items: latest purchase price. Batch items
    (decoction): cost of one batch's raw ingredients / what one batch makes."""
    costs = {i.id: Decimal(i.cost_per_unit_paise or 0) for i in ingredients}
    all_raw = {i.id: Decimal(i.cost_per_unit_paise or 0) for i in db.scalars(select(Ingredient))}
    for i in ingredients:
        if i.kind == IngredientKind.prep:
            r = resolve_recipe(db, prep_ingredient_id=i.id)
            if r and r.yield_qty:
                batch = sum((ln.qty * all_raw.get(ln.ingredient_id, ZERO) for ln in r.lines), ZERO)
                costs[i.id] = (batch / r.yield_qty).quantize(Q3)
    return costs


# ---------------------------------------------------------------- wastage
def record_wastage(
    db: Session,
    *,
    ingredient: Ingredient | None,
    menu_item: MenuItem | None,
    qty: Decimal,
    reason: WastageReason,
    note: str,
    user_id: uuid.UUID,
    is_owner: bool,
) -> WastageEntry:
    if reason in OWNER_ONLY_REASONS and not is_owner:
        raise PermissionError(f"Only the owner can record '{reason.value}'")
    now = utcnow()
    bdate = business_date_of(now)

    recipe_id = None
    if menu_item is not None:
        if qty != qty.to_integral_value():
            raise DayEndError("A wasted menu item is counted in whole servings")
        recipe = resolve_recipe(db, menu_item_id=menu_item.id)
        if recipe is None:
            raise DayEndError(
                f"{menu_item.name} has no recipe, so the app cannot tell what was lost. "
                "Record the ingredients instead."
            )
        recipe_id = recipe.id
        fixed = set(
            db.scalars(
                select(Ingredient.id).where(
                    Ingredient.id.in_([ln.ingredient_id for ln in recipe.lines]),
                    Ingredient.scales_with_size.is_(False),
                )
            )
        )
        used = consumption_for_line(
            {ln.ingredient_id: ln.qty for ln in recipe.lines}, int(qty), [], fixed
        )
    else:
        used = {ingredient.id: qty.quantize(Q3)}

    targets = db.scalars(select(Ingredient).where(Ingredient.id.in_(used))).all()
    costs = unit_costs(db, list(targets))
    entry = WastageEntry(
        ingredient_id=ingredient.id if ingredient else None,
        menu_item_id=menu_item.id if menu_item else None,
        recipe_id=recipe_id,
        qty=qty,
        reason=reason,
        note=note,
        value_paise=_paise(sum((q * costs.get(i, ZERO) for i, q in used.items()), ZERO)),
        business_date=bdate,
        created_by=user_id,
        created_at=now,
    )
    db.add(entry)
    db.flush()
    for ingredient_id, q in sorted(used.items()):
        if q:
            db.add(
                StockLedger(
                    ingredient_id=ingredient_id,
                    qty_delta=-q,
                    reason=LedgerReason.wastage,
                    ref_type="wastage",
                    ref_id=entry.id,
                    business_date=bdate,
                    created_by=user_id,
                )
            )
    return entry


# ---------------------------------------------------------------- movements
@dataclass
class Movement:
    opening: Decimal = ZERO  # everything before the day
    stock_in: Decimal = ZERO
    prep_in: Decimal = ZERO
    prep_out: Decimal = ZERO  # positive = used in batches
    sold: Decimal = ZERO  # positive = used by sales
    wasted: Decimal = ZERO  # positive
    other: Decimal = ZERO  # voids, late-bill corrections and similar on the day

    @property
    def expected(self) -> Decimal:
        return (
            self.opening
            + self.stock_in
            + self.prep_in
            - self.prep_out
            - self.sold
            - self.wasted
            + self.other
        )

    @property
    def expected_usage(self) -> Decimal:
        """What the SOP says was used: by sales and by batches."""
        return self.sold + self.prep_out


def movements(
    db: Session, bdate: date, ingredient_ids: set[uuid.UUID], *, until: datetime | None = None
) -> dict[uuid.UUID, Movement]:
    """Ledger totals per ingredient for one business day. The day's own closing
    adjustment is never part of 'expected' (it is the answer, not an input).
    `until` freezes the breakdown of an approved day (later late-bill rows excluded)."""
    before = (StockLedger.business_date < bdate).label("before_day")
    q = (
        select(
            StockLedger.ingredient_id,
            StockLedger.reason,
            StockLedger.ref_type,
            before,
            func.sum(StockLedger.qty_delta),
        )
        .where(
            StockLedger.ingredient_id.in_(ingredient_ids),
            StockLedger.business_date <= bdate,
        )
        # One labelled expression: written twice, Postgres sees two different
        # parameters and refuses the GROUP BY.
        .group_by(StockLedger.ingredient_id, StockLedger.reason, StockLedger.ref_type, before)
    )
    if until is not None:
        q = q.where(StockLedger.created_at <= until)
    out: dict[uuid.UUID, Movement] = defaultdict(Movement)
    for ingredient_id, reason, ref_type, before, total in db.execute(q):
        m = out[ingredient_id]
        total = Decimal(total)
        if before or reason == LedgerReason.opening:
            m.opening += total  # a first-day opening count IS the opening
        elif reason == LedgerReason.count_adjustment and ref_type == "day_count":
            continue
        elif reason == LedgerReason.stock_in:
            m.stock_in += total
        elif reason == LedgerReason.prep_in:
            m.prep_in += total
        elif reason == LedgerReason.prep_out:
            m.prep_out -= total
        elif reason == LedgerReason.sale:
            m.sold -= total
        elif reason == LedgerReason.wastage:
            m.wasted -= total
        else:
            m.other += total
    return out


# ---------------------------------------------------------------- the count
def _tolerance_breached(m: Movement, variance: Decimal, tolerance_bp: int) -> bool:
    if variance == 0:
        return False
    usage = m.expected_usage
    if usage <= 0:
        return True  # nothing should have moved, yet the shelf disagrees
    return abs(variance) > usage * Decimal(tolerance_bp) / Decimal(10000)


def find_day(db: Session, bdate: date) -> DayCount:
    """Read-only: the day's count, or an unsaved empty one. Screens load the
    sheet and the report at the same moment, so reads must never insert."""
    dc = db.scalar(
        select(DayCount)
        .where(DayCount.business_date == bdate)
        .options(selectinload(DayCount.lines))
    )
    return dc or DayCount(business_date=bdate, status=DayCountStatus.counting, lines=[])


def get_or_create_day(db: Session, bdate: date) -> DayCount:
    """For writes. Two tablets may submit at once: the loser of the insert race
    picks up the winner's row instead of failing on the unique date."""
    dc = db.scalar(
        select(DayCount)
        .where(DayCount.business_date == bdate)
        .options(selectinload(DayCount.lines))
    )
    if dc is not None:
        return dc
    try:
        with db.begin_nested():
            dc = DayCount(business_date=bdate, status=DayCountStatus.counting)
            db.add(dc)
            db.flush()
    except IntegrityError:
        dc = db.scalar(
            select(DayCount)
            .where(DayCount.business_date == bdate)
            .options(selectinload(DayCount.lines))
        )
    db.refresh(dc, ["lines"])
    return dc


@dataclass
class CountIn:
    ingredient_id: uuid.UUID
    packs: list[PackQty]
    loose_qty: Decimal


@dataclass
class SubmitResult:
    status: DayCountStatus
    recount: list[uuid.UUID] = field(default_factory=list)


def submit_counts(
    db: Session,
    bdate: date,
    counts: list[CountIn],
    user_id: uuid.UUID,
    *,
    ask_recount: bool = True,
) -> SubmitResult:
    """Blind: the result says only which items to count again, never why."""
    dc = get_or_create_day(db, bdate)
    if dc.status == DayCountStatus.approved:
        raise DayLocked("This day is already closed by the owner")
    if not counts:
        raise DayEndError("Count at least one item")
    ingredients = {
        i.id: i
        for i in db.scalars(
            select(Ingredient).where(Ingredient.id.in_([c.ingredient_id for c in counts]))
        )
    }
    by_ingredient = {ln.ingredient_id: ln for ln in dc.lines}
    now = utcnow()
    for c in counts:
        ing = ingredients.get(c.ingredient_id)
        if ing is None:
            raise DayEndError("Unknown item in the count")
        try:
            entered, counted = _convert_packs(db, ing, c.packs, c.loose_qty)
        except StockError as e:
            raise DayEndError(str(e)) from None
        line = by_ingredient.get(ing.id)
        if line is None:
            line = DayCountLine(ingredient_id=ing.id)
            dc.lines.append(line)
            by_ingredient[ing.id] = line
        elif line.recount_requested:
            line.recounted = True
        line.entered, line.loose_qty, line.counted_qty = entered, c.loose_qty, counted
        line.counted_by, line.counted_at = user_id, now
    db.flush()

    ids = set(by_ingredient)
    moves = movements(db, bdate, ids)
    tol = {
        i.id: i.tolerance_bp for i in db.scalars(select(Ingredient).where(Ingredient.id.in_(ids)))
    }
    recount = []
    for ing_id, line in by_ingredient.items():
        m = moves[ing_id]
        if (
            ask_recount
            and not line.recount_requested
            and not line.recounted
            and _tolerance_breached(m, line.counted_qty - m.expected, tol[ing_id])
        ):
            line.recount_requested = True
            recount.append(ing_id)
    # Items asked to recount but not yet recounted keep the day open.
    pending = [i for i, ln in by_ingredient.items() if ln.recount_requested and not ln.recounted]
    if pending:
        dc.status = DayCountStatus.counting
        return SubmitResult(DayCountStatus.counting, sorted(pending, key=str))
    dc.status = DayCountStatus.submitted
    dc.submitted_by, dc.submitted_at = user_id, now
    return SubmitResult(DayCountStatus.submitted, recount)


# ---------------------------------------------------------------- report + approve
@dataclass
class ReportLine:
    ingredient: Ingredient
    move: Movement
    expected: Decimal
    counted: Decimal
    cost: Decimal
    recounted: bool
    has_opening: bool

    @property
    def variance(self) -> Decimal:
        return self.counted - self.expected

    @property
    def variance_paise(self) -> int:
        return _paise(self.variance * self.cost)

    @property
    def actual_usage(self) -> Decimal:
        return self.move.expected_usage - self.variance

    @property
    def adherence_pct(self) -> Decimal | None:
        if self.actual_usage <= 0 or self.move.expected_usage <= 0:
            return None
        return (self.move.expected_usage / self.actual_usage * 100).quantize(Decimal("0.1"))

    @property
    def flagged(self) -> bool:
        return _tolerance_breached(self.move, self.variance, self.ingredient.tolerance_bp)


def report_lines(db: Session, dc: DayCount) -> list[ReportLine]:
    ids = {ln.ingredient_id for ln in dc.lines}
    if not ids:
        return []
    ingredients = {i.id: i for i in db.scalars(select(Ingredient).where(Ingredient.id.in_(ids)))}
    approved = dc.status == DayCountStatus.approved
    moves = movements(db, dc.business_date, ids, until=dc.approved_at if approved else None)
    costs = {} if approved else unit_costs(db, list(ingredients.values()))
    opened = physically_counted(db, before=dc.business_date)
    out = []
    for ln in sorted(dc.lines, key=lambda x: ingredients[x.ingredient_id].name.lower()):
        m = moves[ln.ingredient_id]
        out.append(
            ReportLine(
                ingredient=ingredients[ln.ingredient_id],
                move=m,
                expected=ln.expected_qty if approved else m.expected,
                counted=ln.counted_qty,
                cost=ln.cost_per_unit_paise if approved else costs.get(ln.ingredient_id, ZERO),
                recounted=ln.recounted,
                has_opening=ln.ingredient_id in opened,
            )
        )
    return out


def approve(db: Session, bdate: date, user_id: uuid.UUID) -> DayCount:
    dc = get_or_create_day(db, bdate)
    if dc.status == DayCountStatus.approved:
        raise DayLocked("This day is already closed")
    if dc.status != DayCountStatus.submitted:
        raise DayEndError("The count is not finished yet (recounts are still pending)")
    lines = report_lines(db, dc)
    now = db.scalar(select(func.now()))  # database clock: compared with ledger created_at
    by_id = {ln.ingredient_id: ln for ln in dc.lines}
    for r in lines:
        row = by_id[r.ingredient.id]
        row.expected_qty = r.expected.quantize(Q3)
        row.cost_per_unit_paise = r.cost
        row.variance_paise = r.variance_paise
        delta = (r.counted - r.expected).quantize(Q3)
        if delta:
            db.add(
                StockLedger(
                    ingredient_id=r.ingredient.id,
                    qty_delta=delta,
                    reason=LedgerReason.count_adjustment,
                    ref_type="day_count",
                    ref_id=dc.id,
                    business_date=bdate,
                    created_by=user_id,
                )
            )
    dc.status = DayCountStatus.approved
    dc.approved_by, dc.approved_at = user_id, now
    return dc


def late_bill_correction(
    db: Session, bdate: date, used: dict[uuid.UUID, Decimal], bill_id: uuid.UUID, user_id
) -> None:
    """A bill from an already-closed day arrives late. Its stock left the shelf
    before the count, so the count already reflects it: add it back for counted
    items, keeping stock on hand equal to the physical count. The report shows
    how much of that day's 'missing' stock these late bills explain."""
    dc = db.scalar(
        select(DayCount)
        .where(DayCount.business_date == bdate, DayCount.status == DayCountStatus.approved)
        .options(selectinload(DayCount.lines))
    )
    if dc is None:
        return
    counted = {ln.ingredient_id for ln in dc.lines}
    for ingredient_id, q in sorted(used.items()):
        if q and ingredient_id in counted:
            db.add(
                StockLedger(
                    ingredient_id=ingredient_id,
                    qty_delta=q,
                    reason=LedgerReason.count_adjustment,
                    ref_type="late_bill",
                    ref_id=bill_id,
                    business_date=bdate,
                    created_by=user_id,
                )
            )


def late_bills_explained(db: Session, dc: DayCount) -> tuple[int, int]:
    """(number of late bills, rupee value in paise they explain) for a closed day."""
    rows = db.execute(
        select(StockLedger.ref_id, StockLedger.ingredient_id, StockLedger.qty_delta).where(
            StockLedger.business_date == dc.business_date, StockLedger.ref_type == "late_bill"
        )
    ).all()
    if not rows:
        return 0, 0
    cost = {ln.ingredient_id: ln.cost_per_unit_paise or ZERO for ln in dc.lines}
    value = sum((Decimal(q) * cost.get(i, ZERO) for _, i, q in rows), ZERO)
    return len({r for r, _, _ in rows}), _paise(value)


__all__ = [
    "CountIn",
    "DayEndError",
    "DayLocked",
    "Movement",
    "ReportLine",
    "SubmitResult",
    "approve",
    "find_day",
    "get_or_create_day",
    "late_bill_correction",
    "late_bills_explained",
    "movements",
    "record_wastage",
    "report_lines",
    "submit_counts",
    "unit_costs",
]
