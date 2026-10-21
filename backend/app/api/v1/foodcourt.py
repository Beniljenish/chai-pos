"""A shop owner's place in a food court (README, "9.11").

The owner sees their court and switches their own outlet's "taking online orders" on
and off. Making courts, and adding or removing outlets, is the super admin's
(api/v1/platform.py): there is deliberately no route here for it.
"""

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import Caller, require_owner
from app.services import online, onlinepay

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


class AcceptingIn(BaseModel):
    accepting_orders: bool


@router.get("/food-court")
def my_food_court(caller: Caller = Depends(require_owner), db: Session = Depends(system_db)):
    out = online.view(db, caller.ctx.shop_id)
    if out.get("court") is not None:
        # What customers paid online for this outlet, and what the operator has paid it so far.
        out["online_money"] = onlinepay.outlet_money(db, caller.ctx.shop_id)
    return out


@router.patch("/food-court/me")
def set_accepting(
    body: AcceptingIn, caller: Caller = Depends(require_owner), db: Session = Depends(system_db)
):
    try:
        online.set_accepting(db, caller.ctx.shop_id, body.accepting_orders)
    except online.OnlineError as e:
        raise fail(e) from None
    return online.view(db, caller.ctx.shop_id)
