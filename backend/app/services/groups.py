"""Order together (README, "9.21").

Friends at one food court add their own dishes to a shared list; the host brings everyone's
dishes into their own cart and pays once. The list holds **ids and quantities only**: prices and
availability are looked up fresh when the host imports it, exactly like "order again", so a group
cannot be used to smuggle a price. Nobody sees another member's phone number, only the name they
joined with. A group lives six hours.
"""

import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models import (
    CustomerAccount,
    FoodCourt,
    FoodCourtOutlet,
    GroupCart,
    GroupLine,
    GroupMember,
)
from app.services import online, ratelimit
from app.services.online import OnlineError

LIFETIME = timedelta(hours=6)
MAX_MEMBERS = 10
MAX_LINES = online.MAX_LINES
MAX_GROUPS_PER_DAY = 5


def _group(db: Session, token: str) -> GroupCart:
    g = db.scalar(select(GroupCart).where(GroupCart.token == token))
    if g is None or g.expires_at < utcnow():
        # the same answer for "never existed" and "ran out", so tokens cannot be probed
        raise OnlineError("group_gone", "This group is not open any more.", 404)
    return g


def _member(db: Session, g: GroupCart, account: CustomerAccount) -> GroupMember:
    m = db.scalar(
        select(GroupMember).where(
            GroupMember.group_id == g.id, GroupMember.customer_id == account.id
        )
    )
    if m is None:
        raise OnlineError("not_in_group", "You are not in this group.", 403)
    return m


def create(db: Session, account: CustomerAccount, slug: str) -> dict:
    court = online._court(db, slug)
    try:
        ratelimit.hit(
            db,
            f"group:{account.id}",
            limit=MAX_GROUPS_PER_DAY,
            window=timedelta(hours=24),
            message="You have started a lot of groups today. Please try tomorrow.",
        )
    except ratelimit.RateLimited as e:
        db.rollback()
        raise OnlineError("too_many_groups", e.message, 429) from None
    g = GroupCart(
        token=secrets.token_urlsafe(9),
        court_id=court.id,
        host_id=account.id,
        expires_at=utcnow() + LIFETIME,
    )
    db.add(g)
    db.flush()
    db.add(GroupMember(group_id=g.id, customer_id=account.id, name=account.name))
    db.commit()
    return state(db, account, g.token)


def join(db: Session, account: CustomerAccount, token: str) -> dict:
    try:
        ratelimit.hit(
            db,
            f"groupjoin:{account.id}",
            limit=30,
            window=timedelta(hours=1),
            message="Too many tries. Please try again later.",
        )
    except ratelimit.RateLimited as e:
        db.rollback()
        raise OnlineError("too_many_tries", e.message, 429) from None
    g = _group(db, token)
    if g.status != "open":
        db.commit()
        raise OnlineError("group_closed", "The host has already gone to pay.", 409)
    have = db.scalars(select(GroupMember).where(GroupMember.group_id == g.id)).all()
    if account.id not in {m.customer_id for m in have}:
        if len(have) >= MAX_MEMBERS:
            db.commit()
            raise OnlineError("group_full", "This group is full.", 409)
        db.add(GroupMember(group_id=g.id, customer_id=account.id, name=account.name))
    db.commit()
    return state(db, account, token)


def state(db: Session, account: CustomerAccount, token: str) -> dict:
    g = _group(db, token)
    me = _member(db, g, account)
    members = db.scalars(
        select(GroupMember).where(GroupMember.group_id == g.id).order_by(GroupMember.joined_at)
    ).all()
    names = {m.customer_id: m.name for m in members}
    court = db.get(FoodCourt, g.court_id)
    lines = db.scalars(select(GroupLine).where(GroupLine.group_id == g.id)).all()
    return {
        "token": g.token,
        "court_slug": court.slug,
        "status": g.status,
        "is_host": g.host_id == me.customer_id,
        "expires_at": g.expires_at,
        "members": [
            {
                "name": m.name,
                "is_me": m.customer_id == account.id,
                "is_host": m.customer_id == g.host_id,
            }
            for m in members
        ],
        "lines": [
            {
                "member": names.get(ln.customer_id, ""),
                "mine": ln.customer_id == account.id,
                "outlet_id": ln.outlet_id,
                "menu_item_id": ln.menu_item_id,
                "modifier_ids": ln.modifier_ids,
                "qty": ln.qty,
            }
            for ln in lines
        ],
    }


def set_lines(db: Session, account: CustomerAccount, token: str, lines: list[dict]) -> dict:
    """Replace this member's dishes. Only their own: nobody can write another member's list."""
    g = _group(db, token)
    me = _member(db, g, account)
    if g.status != "open":
        raise OnlineError("group_closed", "The host has already gone to pay.", 409)
    if len(lines) > MAX_LINES:
        raise OnlineError("order_too_big", "That is a lot for one person. Split it up.", 422)
    ok_outlets = set(
        db.scalars(select(FoodCourtOutlet.id).where(FoodCourtOutlet.court_id == g.court_id))
    )
    if any(ln["outlet_id"] not in ok_outlets for ln in lines):
        raise OnlineError("not_found", "No such outlet in this food court.", 404)
    db.execute(
        delete(GroupLine).where(GroupLine.group_id == g.id, GroupLine.customer_id == me.customer_id)
    )
    for ln in lines:
        db.add(
            GroupLine(
                group_id=g.id,
                customer_id=me.customer_id,
                outlet_id=ln["outlet_id"],
                menu_item_id=ln["menu_item_id"],
                modifier_ids=[str(m) for m in ln["modifier_ids"]],
                qty=ln["qty"],
            )
        )
    db.commit()
    return state(db, account, token)


def close(db: Session, account: CustomerAccount, token: str) -> dict:
    g = _group(db, token)
    me = _member(db, g, account)
    if g.host_id != me.customer_id:
        raise OnlineError("not_host", "Only the host can do this.", 403)
    g.status = "closed"
    db.commit()
    return state(db, account, token)
