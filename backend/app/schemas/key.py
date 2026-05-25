"""Pydantic request/response schemas for key management (Phase 6)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.key_request import InferenceProfileRefOut


class KeyOut(BaseModel):
    """A provisioned key — no bearer token (shown once at provision/regenerate only)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    developer_id: uuid.UUID
    developer_username: str
    developer_display_name: str
    cost_centre_id: uuid.UUID
    cost_centre_code: str
    cost_centre_name: str
    iam_username: str
    status: str
    allowed_models: list[str]
    rolling_limit: float | None
    rolling_period_days: int | None
    rolling_spend: float
    lifetime_budget: float | None
    lifetime_spend: float
    expires_at: datetime | None
    token_retrieved_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None
    inference_profiles: list[InferenceProfileRefOut]


class KeyConstraintsUpdate(BaseModel):
    """Optional constraint updates for PATCH /{key_id}/constraints."""

    allowed_models: list[str] | None = None
    rolling_limit: float | None = Field(default=None, ge=0)
    rolling_period_days: int | None = Field(default=None, ge=1)
    lifetime_budget: float | None = Field(default=None, ge=0)
    expiry_days: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None
