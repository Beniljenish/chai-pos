"""What a customer at a food court can do, with no login (README, "9.11").

Deliberately narrow. Anyone can read the outlets of ONE food court and an
outlet's menu, read one order back through a signed
link. Nothing here reads or writes anything else, and the shop a request touches
is decided by the food court's own outlet list, never by anything sent.
"""

import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.customer_accounts import Customer, current_customer
from app.api.v1.foodcourt import fail, system_db
from app.services import online

router = APIRouter(prefix="/public", tags=["public"])


class ItemIn(BaseModel):
    menu_item_id: uuid.UUID
    qty: int = Field(ge=1, le=online.MAX_QTY)


class PublicOrderIn(BaseModel):
    request_id: uuid.UUID  # the page makes one per order, so a double tap is one order
    note: str = Field(default="", max_length=120)
    message_ok: bool = False
    items: list[ItemIn] = Field(min_length=1, max_length=online.MAX_LINES)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/courts")
def courts(response: Response, c: Customer = Depends(current_customer)):
    """The food courts to choose from. Signed-in customers only: the list is the way in
    for someone who did not scan a QR."""
    _no_store(response)
    return {"courts": online.public_courts(c.db)}


@router.get("/courts/{slug}")
def court(slug: str, response: Response, db: Session = Depends(system_db)):
    _no_store(response)
    try:
        return online.public_court(db, slug)
    except online.OnlineError as e:
        raise fail(e) from None


@router.get("/courts/{slug}/outlets/{outlet_id}/menu")
def menu(slug: str, outlet_id: uuid.UUID, response: Response, db: Session = Depends(system_db)):
    _no_store(response)
    try:
        return online.public_menu(db, slug, outlet_id)
    except online.OnlineError as e:
        raise fail(e) from None


@router.post("/courts/{slug}/outlets/{outlet_id}/orders", status_code=201)
def place_order(
    slug: str,
    outlet_id: uuid.UUID,
    body: PublicOrderIn,
    response: Response,
    c: Customer = Depends(current_customer),
):
    """Needs a customer account. The name and phone on the order are the account's."""
    _no_store(response)
    try:
        return online.place_order(
            c.db,
            slug,
            outlet_id,
            online.OrderInput(
                request_id=body.request_id,
                customer_id=c.account.id,
                name=c.account.name,
                phone=c.account.phone,
                note=body.note,
                message_ok=body.message_ok,
                items=[(i.menu_item_id, i.qty) for i in body.items],
            ),
        )
    except online.OnlineError as e:
        raise fail(e) from None


@router.get("/orders/{status_key}")
def order_status(status_key: str, response: Response):
    _no_store(response)
    try:
        return online.public_order(status_key)
    except online.OnlineError as e:
        raise fail(e) from None
