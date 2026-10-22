"""Link several outlets' owner logins and see them together (README, "9.19")."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.api.deps import Caller, require_owner
from app.schemas import _normalise_phone
from app.services import auth as auth_service
from app.services import links, online

router = APIRouter(tags=["outlets"])


class LinkIn(BaseModel):
    phone: str
    password: str = Field(min_length=1, max_length=128)

    _phone = field_validator("phone")(_normalise_phone)


def _overview(caller: Caller) -> dict:
    with online.system_session() as db:
        return {"outlets": links.overview(db, caller.user)}


@router.get("/links")
def my_outlets(caller: Caller = Depends(require_owner)) -> dict:
    return _overview(caller)


@router.post("/links", status_code=201)
def link_outlet(body: LinkIn, caller: Caller = Depends(require_owner)) -> dict:
    try:
        with online.system_session() as db:
            links.link(db, caller.user, body.phone, body.password)
    except auth_service.LockedOut as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e)) from None
    except auth_service.AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from None
    except links.LinkError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None
    return _overview(caller)


@router.delete("/links/{user_id}")
def unlink_outlet(user_id: uuid.UUID, caller: Caller = Depends(require_owner)) -> dict:
    with online.system_session() as db:
        if not links.unlink(db, caller.user.id, user_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such link")
    return _overview(caller)
