"""User listing endpoint (Phase 3) — admin-only, supports the owner picker.

Mounted under ``/api`` → ``/api/users``.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserListItem

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserListItem])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> list[User]:
    """List all users ordered by username (admin only)."""
    return list(db.scalars(select(User).order_by(User.username)).all())
