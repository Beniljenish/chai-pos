from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import Caller, get_caller_even_if_password_pending
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas import LoginIn, PasswordChangeIn, RefreshIn, TokenPair, UserOut
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenPair)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenPair:
    try:
        return auth_service.login(db, body.phone, body.password)
    except auth_service.LockedOut as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e)) from None
    except auth_service.AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from None


@router.get("/dev-login")
def dev_login() -> dict:
    """Whether this server is in local test mode (no password needed). Public:
    the login screen asks before anyone has signed in."""
    return {"enabled": get_settings().dev_login}


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
def me(caller: Caller = Depends(get_caller_even_if_password_pending)):
    return caller.user


@router.post("/password", response_model=TokenPair)
def change_password(
    body: PasswordChangeIn, caller: Caller = Depends(get_caller_even_if_password_pending)
) -> TokenPair:
    """Anyone, for their own account. Returns new tokens: all other sessions end."""
    try:
        return auth_service.change_own_password(
            caller.db, caller.user, body.current_password, body.new_password
        )
    except auth_service.AuthError as e:
        caller.db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None
