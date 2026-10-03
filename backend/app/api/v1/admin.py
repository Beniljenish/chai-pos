"""Owner-managed resources: the shop profile, staff accounts and billing devices.

Note how none of these handlers mention shop_id in a WHERE clause: the tenant
session adds it. A lookup of another shop's id simply finds nothing -> 404.
We return 404, not 403, so a caller cannot even learn that the id exists.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.common import unprocessable
from app.api.deps import Caller, get_caller, require_owner
from app.core.security import hash_password
from app.models import Device, GstType, Shop, User
from app.schemas import (
    DeviceCreate,
    DeviceOut,
    DeviceUpdate,
    ShopOut,
    ShopUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter()


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


# ---------------- shop ----------------
def _current_shop(caller: Caller) -> Shop:
    shop = caller.db.scalar(select(Shop).where(Shop.id == caller.ctx.shop_id))
    if shop is None:
        raise _not_found()
    return shop


@router.get("/shop", response_model=ShopOut, tags=["shop"])
def get_shop(caller: Caller = Depends(get_caller)):
    return _current_shop(caller)


@router.patch("/shop", response_model=ShopOut, tags=["shop"])
def update_shop(body: ShopUpdate, caller: Caller = Depends(require_owner)):
    shop = _current_shop(caller)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(shop, field, value)
    # Checked on the result, not the request: a PATCH that only flips gst_type
    # must still have a GSTIN on file. Only when GST settings are being changed,
    # so a shop saved before this rule can still be renamed.
    touches_gst = "gst_type" in changes or "gstin" in changes
    registered = shop.gst_type in (GstType.regular, GstType.composition)
    if touches_gst and registered and not shop.gstin:
        caller.db.rollback()
        raise unprocessable(
            "A registered shop (regular or composition) must have a GSTIN: "
            "it is printed on every bill"
        )
    if shop.gstin:
        # The GSTIN's first two digits ARE the state of registration, and the
        # state decides CGST+SGST, so they can never disagree.
        shop.state_code = shop.gstin[:2]
    caller.db.commit()
    return shop


# ---------------- users ----------------
@router.get("/users", response_model=list[UserOut], tags=["users"])
def list_users(caller: Caller = Depends(require_owner)):
    return caller.db.scalars(select(User).order_by(User.created_at)).all()


@router.post("/users", response_model=UserOut, status_code=201, tags=["users"])
def create_user(body: UserCreate, caller: Caller = Depends(require_owner)):
    user = User(
        name=body.name,
        phone=body.phone,
        role=body.role,
        password_hash=hash_password(body.password),
    )
    caller.db.add(user)
    try:
        caller.db.commit()
    except IntegrityError:
        caller.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Phone number already registered") from None
    return user


def _get_user(caller: Caller, user_id: uuid.UUID) -> User:
    user = caller.db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise _not_found()
    return user


@router.get("/users/{user_id}", response_model=UserOut, tags=["users"])
def get_user(user_id: uuid.UUID, caller: Caller = Depends(require_owner)):
    return _get_user(caller, user_id)


@router.patch("/users/{user_id}", response_model=UserOut, tags=["users"])
def update_user(user_id: uuid.UUID, body: UserUpdate, caller: Caller = Depends(require_owner)):
    user = _get_user(caller, user_id)
    data = body.model_dump(exclude_unset=True)
    if user.id == caller.user.id and data.get("is_active") is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate yourself")
    if "password" in data:
        user.password_hash = hash_password(data.pop("password"))
    for field, value in data.items():
        setattr(user, field, value)
    caller.db.commit()
    return user


# ---------------- devices ----------------
@router.get("/devices", response_model=list[DeviceOut], tags=["devices"])
def list_devices(caller: Caller = Depends(get_caller)):
    return caller.db.scalars(select(Device).order_by(Device.code)).all()


@router.post("/devices", response_model=DeviceOut, status_code=201, tags=["devices"])
def register_device(body: DeviceCreate, caller: Caller = Depends(require_owner)):
    # Codes are C1, C2, ... per shop. Two owners registering at the same instant
    # would race; the unique (shop_id, code) constraint turns that into a 409.
    count = caller.db.scalar(select(func.count()).select_from(Device)) or 0
    device = Device(name=body.name, code=f"C{count + 1}")
    caller.db.add(device)
    try:
        caller.db.commit()
    except IntegrityError:
        caller.db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Device code clash, retry") from None
    return device


def _get_device(caller: Caller, device_id: uuid.UUID) -> Device:
    device = caller.db.scalar(select(Device).where(Device.id == device_id))
    if device is None:
        raise _not_found()
    return device


@router.get("/devices/{device_id}", response_model=DeviceOut, tags=["devices"])
def get_device(device_id: uuid.UUID, caller: Caller = Depends(get_caller)):
    return _get_device(caller, device_id)


@router.patch("/devices/{device_id}", response_model=DeviceOut, tags=["devices"])
def update_device(
    device_id: uuid.UUID, body: DeviceUpdate, caller: Caller = Depends(require_owner)
):
    device = _get_device(caller, device_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(device, field, value)
    caller.db.commit()
    return device
