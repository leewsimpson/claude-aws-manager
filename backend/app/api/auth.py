"""Auth endpoints: hard-coded PoC login + current-user lookup.

Mounted under ``/api`` → ``POST /api/auth/login``, ``GET /api/auth/me``.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import CurrentUser, LoginRequest, LoginResponse, UserSummary

router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid username or password",
)


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Validate credentials and return a JWT plus the user summary."""
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not user.is_active or user.password_hash is None:
        raise _INVALID_CREDENTIALS
    if not verify_password(body.password, user.password_hash):
        raise _INVALID_CREDENTIALS

    token = create_access_token(str(user.id))
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=UserSummary.model_validate(user),
    )


@router.get("/me", response_model=CurrentUser)
def me(user: User = Depends(get_current_user)) -> CurrentUser:
    """Return the authenticated user's profile."""
    return CurrentUser.model_validate(user)
