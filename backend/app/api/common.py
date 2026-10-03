import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def get_or_404[T](db: Session, model: type[T], obj_id: uuid.UUID) -> T:
    """Tenant-scoped lookup: another shop's id is indistinguishable from a missing one."""
    obj = db.scalar(select(model).where(model.id == obj_id))
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return obj


def commit_or_409(db: Session, message: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, message) from None


def unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)
