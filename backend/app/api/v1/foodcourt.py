"""A shop owner's place in a food court (README, "9.11").

The owner sees their court and switches their own outlet's "taking online orders" on
and off. Making courts, and adding or removing outlets, is the super admin's
(api/v1/platform.py): there is deliberately no route here for it.
"""

from collections.abc import Iterator
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import Caller, require_owner
from app.services import extras, online, onlinepay

router = APIRouter(tags=["food court"])


def system_db() -> Iterator[Session]:
    """A session that sees every shop. Used only by services/online.py and
    services/platform.py, which are given the caller's shop id from the token (or the
    super admin's ids) and check the rest by hand."""
    db = online.system_session()
    try:
        yield db
    finally:
        db.close()


def fail(e: online.OnlineError) -> HTTPException:
    return HTTPException(e.status, {"code": e.code, "message": e.message, **e.extra})


class OutletSettingsIn(BaseModel):
    """What an owner can change about their outlet's place in the court. Send only what changes;
    a usual wait of 0 means "not said"."""

    accepting_orders: bool | None = None
    prep_minutes: int | None = Field(default=None, ge=0, le=180)
    pickup_enabled: bool | None = None
    pickup_capacity: int | None = Field(default=None, ge=1, le=60)
    busy_pause_on: bool | None = None
    busy_limit: int | None = Field(default=None, ge=2, le=40)
    resume_now: bool | None = None  # open again before a pause runs out
    # loyalty: every N-th order earns this much off the next; send both (0 and 0 switches it off)
    loyalty_every: int | None = Field(default=None, ge=0, le=50)
    loyalty_reward_paise: int | None = Field(default=None, ge=0, le=100_000)


@router.get("/food-court")
def my_food_court(caller: Caller = Depends(require_owner), db: Session = Depends(system_db)):
    out = online.view(db, caller.ctx.shop_id)
    if out.get("court") is not None:
        # What customers paid online for this outlet, and what the operator has paid it so far.
        out["online_money"] = onlinepay.outlet_money(db, caller.ctx.shop_id)
        out["ratings"] = extras.ratings_for_shop(db, caller.ctx.shop_id)
    return out


@router.patch("/food-court/me")
def set_accepting(
    body: OutletSettingsIn,
    caller: Caller = Depends(require_owner),
    db: Session = Depends(system_db),
):
    try:
        if body.accepting_orders is not None:
            online.set_accepting(db, caller.ctx.shop_id, body.accepting_orders)
        if "prep_minutes" in body.model_fields_set:
            extras.set_prep_minutes(db, caller.ctx.shop_id, body.prep_minutes or None)
        if body.pickup_enabled is not None or body.pickup_capacity is not None:
            online.set_pickup(db, caller.ctx.shop_id, body.pickup_enabled, body.pickup_capacity)
        if body.loyalty_every is not None or body.loyalty_reward_paise is not None:
            online.set_loyalty(
                db, caller.ctx.shop_id, body.loyalty_every, body.loyalty_reward_paise
            )
        if body.busy_pause_on is not None or body.busy_limit is not None or body.resume_now:
            online.set_busy(
                db, caller.ctx.shop_id, body.busy_pause_on, body.busy_limit, bool(body.resume_now)
            )
    except online.OnlineError as e:
        raise fail(e) from None
    return online.view(db, caller.ctx.shop_id)


@router.get("/food-court/statement")
def my_statement(
    start: date = Query(alias="from"),
    end: date = Query(alias="to"),
    caller: Caller = Depends(require_owner),
    db: Session = Depends(system_db),
) -> dict:
    """This outlet's online sales, refunds, the fee and what is still owed, for a range."""
    if online.my_outlet(db, caller.ctx.shop_id) is None:
        raise HTTPException(404, "This shop is not in a food court")
    try:
        return onlinepay.statement(db, caller.ctx.shop_id, start, end)
    except online.OnlineError as e:
        raise fail(e) from None
