"""A shop owner's place in a food court (README, "9.11")."""

import uuid
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import Caller, require_owner
from app.services import online

router = APIRouter(tags=["food court"])


def system_db() -> Iterator[Session]:
    """A session that sees every shop. Used only by services/online.py, which is
    given the caller's shop id from the token and checks the rest by hand."""
    db = online.system_session()
    try:
        yield db
    finally:
        db.close()


def fail(e: online.OnlineError) -> HTTPException:
    return HTTPException(e.status, {"code": e.code, "message": e.message, **e.extra})


class CourtIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)


class JoinIn(BaseModel):
    code: str = Field(min_length=4, max_length=12)


class AcceptingIn(BaseModel):
    accepting_orders: bool


@router.get("/food-court")
def my_food_court(caller: Caller = Depends(require_owner), db: Session = Depends(system_db)):
    return online.view(db, caller.ctx.shop_id)


@router.post("/food-court", status_code=201)
def create_food_court(
    body: CourtIn, caller: Caller = Depends(require_owner), db: Session = Depends(system_db)
):
    try:
        online.create_court(db, caller.ctx.shop_id, body.name)
    except online.OnlineError as e:
        raise fail(e) from None
    return online.view(db, caller.ctx.shop_id)


@router.post("/food-court/join")
def join_food_court(
    body: JoinIn, caller: Caller = Depends(require_owner), db: Session = Depends(system_db)
):
    try:
        online.join_court(db, caller.ctx.shop_id, body.code)
    except online.OnlineError as e:
        raise fail(e) from None
    return online.view(db, caller.ctx.shop_id)


@router.patch("/food-court/me")
def set_accepting(
    body: AcceptingIn, caller: Caller = Depends(require_owner), db: Session = Depends(system_db)
):
    try:
        online.set_accepting(db, caller.ctx.shop_id, body.accepting_orders)
    except online.OnlineError as e:
        raise fail(e) from None
    return online.view(db, caller.ctx.shop_id)


@router.post("/food-court/code")
def new_code(caller: Caller = Depends(require_owner), db: Session = Depends(system_db)):
    try:
        online.new_join_code(db, caller.ctx.shop_id)
    except online.OnlineError as e:
        raise fail(e) from None
    return online.view(db, caller.ctx.shop_id)


@router.delete("/food-court/outlets/{outlet_id}")
def remove_outlet(
    outlet_id: uuid.UUID, caller: Caller = Depends(require_owner), db: Session = Depends(system_db)
):
    try:
        online.remove_outlet(db, caller.ctx.shop_id, outlet_id)
    except online.OnlineError as e:
        raise fail(e) from None
    return online.view(db, caller.ctx.shop_id)
