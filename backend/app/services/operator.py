"""The food court operator's overview (README, "9.21"): every outlet side by side, the busy hours,
a scorecard per outlet, and what each is owed now (the settlement sheet).

Everything here is read from the records through each outlet's own tenant session, so shop
isolation is as it always was. A figure that cannot be known is `null`, never a guess: an outlet
with no collected orders has no average wait."""

import uuid
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    FoodCourt,
    FoodCourtOutlet,
    OnlineOrder,
    Order,
    OrderEvent,
    OrderEventKind,
    OrderStatus,
    Role,
    Shop,
    User,
)
from app.services import extras, online, onlinepay


def _outlet_figures(shop_id: uuid.UUID, start: date, end: date, fee_bp: int, tz: ZoneInfo) -> dict:
    """Orders, money and speed for one outlet in the range, plus its hour-of-week counts."""
    with online.shop_session(shop_id) as db:
        rows = db.execute(
            select(OnlineOrder, Order)
            .join(Order, Order.id == OnlineOrder.order_id)
            .where(OnlineOrder.business_date >= start, OnlineOrder.business_date <= end)
        ).all()
        orders = len(rows)
        cancelled = sum(1 for _, o in rows if o.status == OrderStatus.cancelled)
        sales = fee = refunds = 0
        grid: dict[tuple[int, int], int] = {}
        waits: list[float] = []
        for oo, o in rows:
            local = o.opened_at.astimezone(tz)
            grid[(local.weekday(), local.hour)] = grid.get((local.weekday(), local.hour), 0) + 1
            paid = int(oo.paid_paise or 0)
            if o.status == OrderStatus.cancelled:
                refunds += paid
                continue
            sales += paid
            fee += onlinepay.fee_of(paid, fee_bp)
            if o.status == OrderStatus.settled or online.public_state(o.state) == "ready":
                last_ready = db.scalar(
                    select(func.max(OrderEvent.at)).where(
                        OrderEvent.order_id == o.id, OrderEvent.kind == OrderEventKind.ready
                    )
                )
                if last_ready is not None and last_ready >= o.opened_at:
                    waits.append((last_ready - o.opened_at).total_seconds() / 60)
        return {
            "orders": orders,
            "cancelled": cancelled,
            "cancel_rate_pct": round(cancelled * 100 / orders, 1) if orders else None,
            "sales_paise": sales,
            "fee_paise": fee,
            "refunds_paise": refunds,
            "avg_wait_min": round(sum(waits) / len(waits), 1) if waits else None,
            "_grid": grid,
        }


def overview(db: Session, start: date, end: date) -> dict:
    tz = ZoneInfo(get_settings().shop_timezone)
    ratings = extras.rating_by_shop(db)
    out = []
    for court in db.scalars(select(FoodCourt).order_by(FoodCourt.created_at)):
        heat = [[0] * 24 for _ in range(7)]
        outlets = []
        rows = db.execute(
            select(FoodCourtOutlet, Shop)
            .join(Shop, Shop.id == FoodCourtOutlet.shop_id)
            .where(FoodCourtOutlet.court_id == court.id)
            .order_by(FoodCourtOutlet.joined_at)
        ).all()
        for o, shop in rows:
            f = _outlet_figures(shop.id, start, end, o.fee_bp, tz)
            for (wd, hr), n in f.pop("_grid").items():
                heat[wd][hr] += n
            rating = ratings.get(shop.id)
            outlets.append(
                {
                    "outlet_id": o.id,
                    "name": shop.name,
                    "fee_bp": o.fee_bp,
                    "rating": rating[0] if rating else None,
                    "rating_count": rating[1] if rating else 0,
                    **f,
                }
            )
        out.append(
            {
                "court_id": court.id,
                "court": court.name,
                "outlets": outlets,
                "totals": {
                    "sales_paise": sum(o["sales_paise"] for o in outlets),
                    "fee_paise": sum(o["fee_paise"] for o in outlets),
                    "orders": sum(o["orders"] for o in outlets),
                },
                "heatmap": heat,  # 7 weekdays (Monday first) x 24 hours, orders placed
                "busiest": _busiest(heat),
            }
        )
    return {"from": start, "to": end, "courts": out}


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _busiest(heat: list[list[int]]) -> list[dict]:
    """The three busiest hours of the week, with how many orders (none when there were none)."""
    cells = [(n, wd, hr) for wd, row in enumerate(heat) for hr, n in enumerate(row) if n > 0]
    cells.sort(key=lambda c: (-c[0], c[1], c[2]))
    return [{"weekday": WEEKDAYS[wd], "hour": hr, "orders": n} for n, wd, hr in cells[:3]]


def settlement(db: Session) -> list[dict]:
    """What each outlet is owed now (all time, after the fee and what was already paid out)."""
    out = []
    for court in db.scalars(select(FoodCourt).order_by(FoodCourt.created_at)):
        rows = db.execute(
            select(FoodCourtOutlet, Shop)
            .join(Shop, Shop.id == FoodCourtOutlet.shop_id)
            .where(FoodCourtOutlet.court_id == court.id)
            .order_by(FoodCourtOutlet.joined_at)
        ).all()
        for _outlet, shop in rows:
            owner = db.scalar(
                select(User)
                .where(User.shop_id == shop.id, User.role == Role.owner)
                .order_by(User.created_at)
            )
            m = onlinepay.outlet_money(db, shop.id)
            out.append(
                {
                    "court": court.name,
                    "outlet": shop.name,
                    "owner": owner.name if owner else "",
                    "owner_phone": owner.phone if owner else "",
                    "paid_paise": m["paid_paise"],
                    "fee_paise": m["fee_paise"],
                    "settled_paise": m["settled_paise"],
                    "owed_paise": m["owed_paise"],
                }
            )
    return out
