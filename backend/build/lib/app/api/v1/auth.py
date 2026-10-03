from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import Caller, get_caller
from app.db.session import get_db
from app.schemas import LoginIn, RefreshIn, TokenPair, UserOut
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenPair)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenPair:
    try:
        return auth_service.login(db, body.phone, body.password)
    except auth_service.AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from None


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshIn, db: Session = Depends(get_db)) -> TokenPair:
    try:
        return auth_service.refresh(db, body.refresh_token)
    except auth_service.AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from None


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshIn, db: Session = Depends(get_db)) -> None:
    auth_service.logout(db, body.refresh_token)


@router.get("/me", response_model=UserOut)
def me(caller: Caller = Depends(get_caller)):
    return caller.user
