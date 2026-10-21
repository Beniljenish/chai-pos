"""What makes a food court customer come back (README, "9.15"): a phone notification when the order
is ready, favourite dishes, a rating after collecting, and each outlet's usual wait."""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models import (
    CustomerAccount,
    CustomerFavourite,
    FoodCourt,
    FoodCourtOutlet,
    MenuItem,
    OnlineOrder,
    Order,
    OrderFeedback,
    PushSubscription,
    Shop,
)
from app.services import online, webpush
from app.services.online import OnlineError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- ready notice (Web Push)
def notify_ready(db: Session, order: Order) -> None:
    """Called after an order's events: once every dish on a customer's online order is ready,
    send their phone one notification. `db` is the outlet's own session. Claimed first (the
    timestamp), so a second call, or two tills reporting together, sends nothing twice."""
    if not webpush.enabled():
        return
    lines = [ln for ln in order.state.get("lines", []) if ln.get("qty", 0) > 0]
    if not lines or not all(ln.get("ready") for ln in lines):
        return
    oo = db.scalar(select(OnlineOrder).where(OnlineOrder.order_id == order.id))
    if oo is None or oo.customer_id is None or oo.ready_notified_at is not None:
        return
    oo.ready_notified_at = utcnow()
    shop_name = db.scalar(select(Shop.name))
    token, customer_id, court_id = oo.token, oo.customer_id, oo.court_id
    db.flush()
    with online.system_session() as sysdb:
        court = sysdb.get(FoodCourt, court_id)
        subs = sysdb.scalars(
            select(PushSubscription).where(PushSubscription.customer_id == customer_id)
        ).all()
        message = {
            "title": f"{token} is ready to collect",
            "body": f"{shop_name} · show your token at the counter",
            "url": f"/order/{court.slug}" if court else "/order",
            "tag": f"order-{token}",
        }
        for sub in subs:
            if webpush.send(sub.endpoint, sub.p256dh, sub.auth, message) == "gone":
                sysdb.delete(sub)  # the phone forgot us: stop trying
        sysdb.commit()


def subscribe(db: Session, account: CustomerAccount, endpoint: str, p256dh: str, auth: str) -> None:
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if sub is None:
        db.add(
            PushSubscription(customer_id=account.id, endpoint=endpoint, p256dh=p256dh, auth=auth)
        )
    else:  # a phone that changed hands: it now belongs to whoever is logged in
        sub.customer_id, sub.p256dh, sub.auth = account.id, p256dh, auth
    db.commit()


def unsubscribe(db: Session, account: CustomerAccount, endpoint: str) -> None:
    sub = db.scalar(
        select(PushSubscription).where(
            PushSubscription.endpoint == endpoint, PushSubscription.customer_id == account.id
        )
    )
    if sub is not None:
        db.delete(sub)
        db.commit()


# ---------------------------------------------------------------- favourites
def favourites(db: Session, customer_id: uuid.UUID) -> list[dict]:
    rows = db.execute(
        select(CustomerFavourite, MenuItem, Shop, FoodCourtOutlet, FoodCourt)
        .join(MenuItem, MenuItem.id == CustomerFavourite.menu_item_id)
        .join(Shop, Shop.id == CustomerFavourite.shop_id)
        .join(FoodCourtOutlet, FoodCourtOutlet.shop_id == CustomerFavourite.shop_id)
        .join(FoodCourt, FoodCourt.id == FoodCourtOutlet.court_id)
        .where(CustomerFavourite.customer_id == customer_id, MenuItem.is_active)
        .order_by(CustomerFavourite.created_at.desc())
    ).all()
    return [
        {
            "menu_item_id": item.id,
            "name": item.name,
            "price_paise": item.price_paise,
            "photo_url": item.photo_url,
            "is_veg": item.is_veg,
            "sold_out": item.is_sold_out,
            "outlet_id": outlet.id,
            "outlet": shop.name,
            "court": court.name,
            "court_slug": court.slug,
        }
        for _fav, item, shop, outlet, court in rows
    ]


def add_favourite(db: Session, customer_id: uuid.UUID, menu_item_id: uuid.UUID) -> None:
    item = db.get(MenuItem, menu_item_id)
    in_a_court = item is not None and db.scalar(
        select(FoodCourtOutlet.id).where(FoodCourtOutlet.shop_id == item.shop_id)
    )
    if item is None or not item.is_active or not in_a_court:
        raise OnlineError("not_found", "No such dish", 404)
    exists = db.scalar(
        select(CustomerFavourite.id).where(
            CustomerFavourite.customer_id == customer_id,
            CustomerFavourite.menu_item_id == menu_item_id,
        )
    )
    if exists is None:
        db.add(
            CustomerFavourite(customer_id=customer_id, shop_id=item.shop_id, menu_item_id=item.id)
        )
        try:
            db.commit()
        except IntegrityError:  # two taps at once
            db.rollback()


def remove_favourite(db: Session, customer_id: uuid.UUID, menu_item_id: uuid.UUID) -> None:
    fav = db.scalar(
        select(CustomerFavourite).where(
            CustomerFavourite.customer_id == customer_id,
            CustomerFavourite.menu_item_id == menu_item_id,
        )
    )
    if fav is not None:
        db.delete(fav)
        db.commit()


# ---------------------------------------------------------------- ratings
def _own_online_order(
    shop_db: Session, key: str, customer_id: uuid.UUID
) -> tuple[OnlineOrder, Order]:
    parsed = online._parse_key(key)
    if parsed is None:
        raise OnlineError("not_found", "No such order", 404)
    _shop_id, order_id = parsed
    oo = shop_db.scalar(select(OnlineOrder).where(OnlineOrder.order_id == order_id))
    order = shop_db.scalar(select(Order).where(Order.id == order_id))
    if oo is None or order is None or oo.customer_id != customer_id:
        raise OnlineError("not_found", "No such order", 404)
    return oo, order


def rate(key: str, customer_id: uuid.UUID, rating: int, comment: str) -> dict:
    """One rating per collected order, by the customer who placed it."""
    parsed = online._parse_key(key)
    if parsed is None:
        raise OnlineError("not_found", "No such order", 404)
    with online.shop_session(parsed[0]) as db:
        oo, order = _own_online_order(db, key, customer_id)
        if online.public_state(order.state) != "collected":
            raise OnlineError(
                "not_collected", "You can rate an order once you have collected it", 409
            )
        db.add(
            OrderFeedback(
                online_order_id=oo.id,
                customer_id=customer_id,
                rating=rating,
                comment=online._clean_text(comment, 200),
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise OnlineError("already_rated", "You have already rated this order", 409) from None
        return {"rating": rating}


def my_rating(key: str, customer_id: uuid.UUID) -> dict:
    parsed = online._parse_key(key)
    if parsed is None:
        raise OnlineError("not_found", "No such order", 404)
    with online.shop_session(parsed[0]) as db:
        oo, _order = _own_online_order(db, key, customer_id)
        fb = db.scalar(select(OrderFeedback).where(OrderFeedback.online_order_id == oo.id))
        return {"rating": fb.rating if fb else None, "comment": fb.comment if fb else ""}


def ratings_for_shop(db: Session, shop_id: uuid.UUID) -> dict:
    """An outlet's average and its latest comments. `db` is a system session, so the shop is
    named in every query."""
    avg, count = db.execute(
        select(func.avg(OrderFeedback.rating), func.count(OrderFeedback.id)).where(
            OrderFeedback.shop_id == shop_id
        )
    ).one()
    recent = db.execute(
        select(OrderFeedback, CustomerAccount.name)
        .join(CustomerAccount, CustomerAccount.id == OrderFeedback.customer_id)
        .where(OrderFeedback.shop_id == shop_id)
        .order_by(OrderFeedback.created_at.desc())
        .limit(10)
    ).all()
    return {
        "average": round(float(avg), 1) if avg is not None else None,
        "count": int(count),
        "recent": [
            {
                "rating": fb.rating,
                "comment": fb.comment,
                "name": name.split()[0] if name else "",
                "at": fb.created_at.isoformat(),
            }
            for fb, name in recent
        ],
    }


def rating_by_shop(db: Session) -> dict[uuid.UUID, tuple[float, int]]:
    """Every outlet's (average, count), for the admin's list."""
    return {
        shop_id: (round(float(avg), 1), int(count))
        for shop_id, avg, count in db.execute(
            select(
                OrderFeedback.shop_id, func.avg(OrderFeedback.rating), func.count(OrderFeedback.id)
            ).group_by(OrderFeedback.shop_id)
        )
    }


# ---------------------------------------------------------------- the outlet's usual wait
def set_prep_minutes(db: Session, shop_id: uuid.UUID, minutes: int | None) -> None:
    mine = online.my_outlet(db, shop_id)
    if mine is None:
        raise OnlineError("not_in_a_court", "This shop is not in a food court", 404)
    mine.prep_minutes = minutes
    db.commit()
