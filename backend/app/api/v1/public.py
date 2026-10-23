"""What a customer at a food court can do, with no login (README, "9.11").

Deliberately narrow. Anyone can read the outlets of ONE food court and an
outlet's menu, read one order back through a signed
link. Nothing here reads or writes anything else, and the shop a request touches
is decided by the food court's own outlet list, never by anything sent.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.customer_accounts import Customer, current_customer
from app.api.v1.foodcourt import fail, system_db
from app.models import DishPhoto
from app.services import online

router = APIRouter(prefix="/public", tags=["public"])


class ItemIn(BaseModel):
    menu_item_id: uuid.UUID
    qty: int = Field(ge=1, le=online.MAX_QTY)
    # The options ticked (Large, less sugar...): ids only, priced by the server.
    modifier_ids: list[uuid.UUID] = Field(default_factory=list, max_length=6)


class PublicOrderIn(BaseModel):
    request_id: uuid.UUID  # the page makes one per order, so a double tap is one order
    note: str = Field(default="", max_length=120)
    message_ok: bool = False
    items: list[ItemIn] = Field(min_length=1, max_length=online.MAX_LINES)
    pickup_at: datetime | None = None
    table_name: str = Field(default="", max_length=20)
    coupon_code: str = Field(default="", max_length=30)


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


@router.get("/dish-photos/{photo_id}")
def dish_photo(photo_id: str, db: Session = Depends(system_db)) -> Response:
    """A dish photo an outlet uploaded. Anyone with the link may look (it is on a public menu);
    the link is the photo's random id. Served as a picture and nothing else."""
    try:
        key = uuid.UUID(photo_id)
    except ValueError:
        raise HTTPException(404, "No such picture") from None
    photo = db.get(DishPhoto, key)
    if photo is None:
        raise HTTPException(404, "No such picture")
    return Response(
        photo.data,
        media_type=photo.content_type,
        headers={
            "Cache-Control": "public, max-age=86400, immutable",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cross-Origin-Resource-Policy": "cross-origin",
        },
    )


@router.get("/courts/{slug}/board")
def board(slug: str, response: Response, db: Session = Depends(system_db)):
    """What the food court's display shows: tokens only, never a name or a number."""
    _no_store(response)
    try:
        return online.board(db, slug)
    except online.OnlineError as e:
        raise fail(e) from None


@router.get("/courts/{slug}/outlets/{outlet_id}/menu")
def menu(slug: str, outlet_id: uuid.UUID, response: Response, db: Session = Depends(system_db)):
    _no_store(response)
    try:
        return online.public_menu(db, slug, outlet_id)
    except online.OnlineError as e:
        raise fail(e) from None


@router.get("/courts/{slug}/outlets/{outlet_id}/slots")
def slots(slug: str, outlet_id: uuid.UUID, response: Response, db: Session = Depends(system_db)):
    _no_store(response)
    try:
        return online.slots(db, slug, outlet_id)
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
                items=[
                    online.Pick(i.menu_item_id, i.qty, tuple(i.modifier_ids)) for i in body.items
                ],
                pickup_at=body.pickup_at,
                table_name=body.table_name,
                coupon_code=body.coupon_code,
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


class AppErrorIn(BaseModel):
    message: str = Field(max_length=2000)
    place: str = Field(default="", max_length=500)
    detail: str = Field(default="", max_length=8000)


@router.post("/app-errors", status_code=204)
def app_error(body: AppErrorIn, request: Request, db: Session = Depends(system_db)) -> Response:
    """An error someone's app ran into (README, "9.28"). No login: it can happen before one, and
    a broken page must still be able to say so. Limited per address so it cannot fill the log."""
    from datetime import timedelta

    from app.api.v1.customer_accounts import client_ip
    from app.services import errors, ratelimit

    try:
        ratelimit.hit(
            db,
            f"apperr:{client_ip(request)}",
            limit=30,
            window=timedelta(hours=1),
            message="Too many reports",
        )
        db.commit()
    except ratelimit.RateLimited:
        db.rollback()
        return Response(status_code=204)  # dropped quietly: the page has nothing to do about it
    errors.record(
        "app",
        body.message,
        place=body.place,
        detail=body.detail,
        agent=request.headers.get("user-agent", ""),
    )
    return Response(status_code=204)
