"""Pydantic schemas for user listing (owner-picker support)."""

import uuid

from pydantic import BaseModel, ConfigDict


class UserListItem(BaseModel):
    """Richer user payload for the admin user list / owner picker."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str
    email: str
    roles: list[str]
    is_active: bool
