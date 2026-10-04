"""Handover counts: pin the day's gap on milk and fruit to the hours it happened.

At a shift change the person handing over counts the items marked "count every
shift", blind. Nothing in stock changes: the day-end count stays the truth.

For each count, at the moment it was made (T):

    expected at T = everything before the day (and the day's opening count)
                    + the day's stock-in, batches and wastage entered by T
                    - sales rung up by T (by when the bill was made on the
                      tablet, not when it reached the server: a tablet that was
                      offline still sold the tea at 10 am)
    gap at T      = counted - expected at T
    gap in period = gap at T - gap at the previous count of that item today

The day-end count is the last point, so the periods add up to the day's
variance. With two counters open at once the shop's stock is shared, so a
period names everyone on duty in it rather than blaming one person.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.time import utcnow
from app.models import (
    Bill,
    DayCount,
    DayCountStatus,
    Device,
    HandoverCount,
    HandoverCountLine,
    Ingredient,
    LedgerReason,
    Shift,
    StockLedger,
    User,
)
from app.services.dayend import (
    ZERO,
    CountIn,
    DayEndError,
    DayLocked,
    _paise,
    find_day,
    report_lines,
    unit_costs,
)
from app.services.stock import StockError, _convert_packs


def record(
    db: Session,
    bdate: date,
    counts: list[CountIn],
    user_id: uuid.UUID,
    shift_id: uuid.UUID | None,
) -> HandoverCount:
    """Blind: the caller learns nothing about what was expected. Counting the
    same shift again replaces that shift's count (a recount, not a new period)."""
    if not counts:
        raise DayEndError("Count at least one item")
    closed = db.scalar(
        select(DayCount.id).where(
            DayCount.business_date == bdate, DayCount.status == DayCountStatus.approved
        )
    )
    if closed is not None:
        raise DayLocked("This day is already closed by the owner")
    ingredients = {
        i.id: i
        for i in db.scalars(
            select(Ingredient).where(Ingredient.id.in_([c.ingredient_id for c in counts]))
        )
    }
    hc = None
    if shift_id is not None:
        hc = db.scalar(
            select(HandoverCount)
            .where(HandoverCount.shift_id == shift_id)
            .options(selectinload(HandoverCount.lines))
        )
    now = utcnow()
    if hc is None:
        hc = HandoverCount(business_date=bdate, shift_id=shift_id, lines=[])
        db.add(hc)
    hc.counted_at, hc.counted_by = now, user_id
    by_ingredient = {ln.ingredient_id: ln for ln in hc.lines}
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
            line = HandoverCountLine(ingredient_id=ing.id)
            hc.lines.append(line)
            by_ingredient[ing.id] = line
        line.entered, line.loose_qty, line.counted_qty = entered, c.loose_qty, counted
    db.flush()
    return hc


def expected_at(
    db: Session, bdate: date, ingredient_ids: set[uuid.UUID], at: datetime
) -> dict[uuid.UUID, Decimal]:
    """Stock each item should have had at `at`, from the ledger (see the module doc)."""
    on_day = StockLedger.business_date == bdate
    q = (
        select(StockLedger.ingredient_id, func.sum(StockLedger.qty_delta))
        .outerjoin(
            Bill,
            and_(
                StockLedger.ref_type == "bill",
                StockLedger.reason == LedgerReason.sale,
                StockLedger.ref_id == Bill.id,
            ),
        )
        .where(
            StockLedger.ingredient_id.in_(ingredient_ids),
            StockLedger.business_date <= bdate,
            or_(
                StockLedger.business_date < bdate,
                and_(on_day, StockLedger.reason == LedgerReason.opening),
                and_(on_day, StockLedger.reason == LedgerReason.sale, Bill.sold_at <= at),
                and_(
                    on_day,
                    StockLedger.reason.not_in(
                        [LedgerReason.opening, LedgerReason.sale, LedgerReason.count_adjustment]
                    ),
                    StockLedger.created_at <= at,
                ),
            ),
        )
        .group_by(StockLedger.ingredient_id)
    )
    out = {i: ZERO for i in ingredient_ids}
    out.update({i: Decimal(q) for i, q in db.execute(q)})
    return out


@dataclass
class PeriodLine:
    ingredient: Ingredient
    expected: Decimal
    counted: Decimal
    gap: Decimal  # counted - expected, at this count
    gap_here: Decimal  # the part of the gap that opened in this period
    gap_here_paise: int


@dataclass
class Period:
    start: datetime
    end: datetime
    is_day_end: bool
    counted_by: uuid.UUID | None
    shift_id: uuid.UUID | None
    on_duty: list[str] = field(default_factory=list)
    lines: list[PeriodLine] = field(default_factory=list)

    @property
    def gap_here_paise(self) -> int:
        return sum(ln.gap_here_paise for ln in self.lines)


def _day_start(bdate: date) -> datetime:
    tz = ZoneInfo(get_settings().shop_timezone)
    return datetime.combine(bdate, time(0, 0), tzinfo=tz).astimezone(UTC)


def _on_duty(db: Session, bdate: date, start: datetime, end: datetime) -> list[str]:
    shifts = db.execute(
        select(Shift.opened_by, Shift.opened_at, Shift.closed_at, Device.name)
        .join(Device, Device.id == Shift.device_id)
        .where(Shift.business_date == bdate)
    ).all()
    names = dict(db.execute(select(User.id, User.name)).all())
    out = []
    for who, opened, closed, device in sorted(shifts, key=lambda r: r[1]):
        if opened < end and (closed is None or closed > start):
            label = f"{names.get(who, '?')} ({device})"
            if label not in out:
                out.append(label)
    return out


def report(db: Session, bdate: date) -> list[Period]:
    counts = db.scalars(
        select(HandoverCount)
        .where(HandoverCount.business_date == bdate)
        .order_by(HandoverCount.counted_at)
        .options(selectinload(HandoverCount.lines))
    ).all()
    if not counts:
        return []
    ids = {ln.ingredient_id for hc in counts for ln in hc.lines}
    ingredients = {i.id: i for i in db.scalars(select(Ingredient).where(Ingredient.id.in_(ids)))}
    costs = unit_costs(db, list(ingredients.values()))

    periods: list[Period] = []
    last_gap: dict[uuid.UUID, Decimal] = {}
    start = _day_start(bdate)
    for hc in counts:
        expected = expected_at(db, bdate, {ln.ingredient_id for ln in hc.lines}, hc.counted_at)
        p = Period(start, hc.counted_at, False, hc.counted_by, hc.shift_id)
        for ln in sorted(hc.lines, key=lambda x: ingredients[x.ingredient_id].name.lower()):
            gap = ln.counted_qty - expected[ln.ingredient_id]
            here = gap - last_gap.get(ln.ingredient_id, ZERO)
            last_gap[ln.ingredient_id] = gap
            p.lines.append(
                PeriodLine(
                    ingredients[ln.ingredient_id],
                    expected[ln.ingredient_id],
                    ln.counted_qty,
                    gap,
                    here,
                    _paise(here * costs.get(ln.ingredient_id, ZERO)),
                )
            )
        periods.append(p)
        start = hc.counted_at

    # The day-end count closes the last period, with the day report's own numbers.
    dc = find_day(db, bdate)
    final = [r for r in report_lines(db, dc) if r.ingredient.id in ids]
    if final and dc.status != DayCountStatus.counting:
        end = dc.submitted_at or utcnow()
        p = Period(start, end, True, dc.submitted_by, None)
        for r in final:
            here = r.variance - last_gap.get(r.ingredient.id, ZERO)
            p.lines.append(
                PeriodLine(
                    r.ingredient, r.expected, r.counted, r.variance, here, _paise(here * r.cost)
                )
            )
        periods.append(p)
    for p in periods:
        p.on_duty = _on_duty(db, bdate, p.start, p.end)
    return periods


__all__ = ["Period", "PeriodLine", "expected_at", "record", "report"]
