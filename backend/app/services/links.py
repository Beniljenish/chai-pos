"""One person, several outlets (README, "9.19").

An owner who runs more than one shop has a login in each. They can *link* the logins (proving
both passwords) and then see every linked outlet side by side: today's sales, what needs them.

**What this is not:** it never issues a token for another shop and never lets one login act
inside another shop. A tablet's saved bills and device belong to one shop, so switching shops on
a tablet would mix their data; to work inside another outlet you still log in there. The overview
is read by the server, one outlet at a time, through that outlet's own tenant session, so shop
isolation is exactly what it was.
"""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.time import business_date, utcnow
from app.models import Bill, BillStatus, OnlineOrder, Order, OrderStatus, Role, Shop, User, UserLink
from app.services import alerts, auth, online


class LinkError(Exception):
    pass


def _pair(db: Session, a: uuid.UUID, b: uuid.UUID) -> None:
    for x, y in ((a, b), (b, a)):
        if (
            db.scalar(
                select(UserLink.id).where(UserLink.user_id == x, UserLink.linked_user_id == y)
            )
            is None
        ):
            db.add(UserLink(user_id=x, linked_user_id=y))


def link(db: Session, me: User, phone: str, password: str) -> None:
    """Link `me` (an owner, already logged in) to another owner, who proves their password here.
    `db` is a system session."""
    if me.role != Role.owner:
        raise LinkError("Only an owner can link outlets")
    other = auth.authenticate(db, phone, password)  # lockout and equal-time rules apply
    if other.role != Role.owner:
        db.rollback()
        raise LinkError("Only an owner's login can be linked")
    if other.id == me.id or other.shop_id == me.shop_id:
        db.rollback()
        raise LinkError("That login is for this same outlet")
    _pair(db, me.id, other.id)
    db.commit()


def unlink(db: Session, me_id: uuid.UUID, other_id: uuid.UUID) -> bool:
    gone = db.execute(
        delete(UserLink).where(
            ((UserLink.user_id == me_id) & (UserLink.linked_user_id == other_id))
            | ((UserLink.user_id == other_id) & (UserLink.linked_user_id == me_id))
        )
    ).rowcount
    db.commit()
    return bool(gone)


def _snapshot(shop_id: uuid.UUID) -> dict:
    today = business_date(utcnow())
    with online.shop_session(shop_id) as db:
        shop = db.scalar(select(Shop))

        def day(d):
            row = db.execute(
                select(func.coalesce(func.sum(Bill.total_paise), 0), func.count()).where(
                    Bill.business_date == d, Bill.status != BillStatus.void
                )
            ).one()
            return int(row[0]), int(row[1])

        sales, bills = day(today)
        waiting = (
            db.scalar(
                select(func.count())
                .select_from(Order)
                .join(OnlineOrder, OnlineOrder.order_id == Order.id)
                .where(Order.status == OrderStatus.open)
            )
            or 0
        )
        needs = sum(1 for a in alerts.build(db, today) if a["urgency"] != "info")
        return {
            "shop_id": shop_id,
            "name": shop.name,
            "sales_paise": sales,
            "bills": bills,
            "needs_you": needs,
            "open_online_orders": int(waiting),
        }


def overview(db: Session, me: User) -> list[dict]:
    """This outlet first, then every linked one that is still an active owner login."""
    out = [{**_snapshot(me.shop_id), "is_me": True, "user_id": me.id}]
    rows = db.execute(
        select(User)
        .join(UserLink, UserLink.linked_user_id == User.id)
        .where(UserLink.user_id == me.id)
        .order_by(User.created_at)
    ).scalars()
    for other in rows:
        if other.role != Role.owner or not other.is_active:
            continue  # switched off or demoted since: not shown, and not read
        out.append({**_snapshot(other.shop_id), "is_me": False, "user_id": other.id})
    return out
