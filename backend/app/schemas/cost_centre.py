"""Pydantic request/response schemas for cost-centre management."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OwnerSummary(BaseModel):
    """An assigned cost-centre owner as returned within a cost centre."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    username: str
    display_name: str
    assigned_at: datetime


class CostCentreCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    budget_cap: float | None = Field(default=None, ge=0)


class CostCentreUpdate(BaseModel):
    """Partial update — ``code`` and ``status`` are intentionally absent."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    budget_cap: float | None = Field(default=None, ge=0)


class OwnerAssign(BaseModel):
    user_id: uuid.UUID


class CostCentre(BaseModel):
    """Full cost-centre response shape (frozen contract)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    status: str
    budget_cap: float | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    owners: list[OwnerSummary] = []
