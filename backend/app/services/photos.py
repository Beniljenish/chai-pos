"""Dish photos taken on the owner's phone, kept in the database (README, "9.17").

The phone shrinks the picture first (800 px, about 300 KB); this checks again and refuses
anything else. A stored photo is shown through a link that carries only its random id, and
its type is decided here from the file's first bytes, never from what the sender claims.
"""

import base64
import binascii
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DishPhoto
from app.services.online import OnlineError

MAX_BYTES = 400_000
MAX_PER_SHOP = 300

_PATH = re.compile(r"^/dish-photos/([0-9a-f]{32})$")


def kind_of(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def store(db: Session, encoded: str) -> str:
    """Save a base64 picture for this shop and return the path to keep on the dish."""
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise OnlineError("bad_photo", "That is not a picture", 422) from None
    if not data or len(data) > MAX_BYTES:
        raise OnlineError("photo_too_big", "That picture is too big. Choose a smaller one.", 422)
    kind = kind_of(data)
    if kind is None:
        raise OnlineError("bad_photo", "Use a JPEG, PNG or WebP picture", 422)
    if (db.scalar(select(func.count()).select_from(DishPhoto)) or 0) >= MAX_PER_SHOP:
        raise OnlineError("too_many_photos", "This shop has reached its photo limit", 422)
    photo = DishPhoto(content_type=kind, data=data)
    db.add(photo)
    db.commit()
    return f"/dish-photos/{photo.id.hex}"


def photo_id(path: str) -> uuid.UUID | None:
    m = _PATH.match(path)
    return uuid.UUID(m.group(1)) if m else None
