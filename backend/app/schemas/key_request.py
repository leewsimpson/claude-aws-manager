"""Pydantic request/response schemas for key request & approval workflow."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApprovalConstraints(BaseModel):
    """Optional constraint overrides supplied at approve time.

    Any field left unset is resolved from global settings.
    """

    allowed_models: list[str] | None = None
    rolling_limit: float | None = Field(default=None, ge=0)
    rolling_period_days: int | None = Field(default=None, ge=1)
    lifetime_budget: float | None = Field(default=None, ge=0)
    expiry_days: int | None = Field(default=None, ge=1)


class KeyRequestCreate(BaseModel):
    cost_centre_id: uuid.UUID
    justification: str | None = None


class KeyRequestReject(BaseModel):
    rejection_reason: str = Field(min_length=1)


class InferenceProfileRefOut(BaseModel):
    """A provisioned inference profile returned within a key response."""

    model_config = ConfigDict(from_attributes=True)

    model_id: str
    profile_arn: str
    profile_name: str


class KeyRequestOut(BaseModel):
    """Full key request response shape."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    developer_id: uuid.UUID
    developer_username: str
    developer_display_name: str
    cost_centre_id: uuid.UUID
    cost_centre_code: str
    cost_centre_name: str
    status: str
    justification: str | None
    rejection_reason: str | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    approved_constraints: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class ProvisionedKeyOut(BaseModel):
    """A provisioned key, including the one-time bearer token."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cost_centre_id: uuid.UUID
    cost_centre_code: str
    iam_username: str
    status: str
    allowed_models: list[str]
    rolling_limit: float | None
    rolling_period_days: int | None
    lifetime_budget: float | None
    expires_at: datetime | None
    bearer_token: str
    inference_profiles: list[InferenceProfileRefOut]


class KeyRequestResult(BaseModel):
    """Combined response for create/approve — always includes the request,
    optionally the provisioned key (None while pending)."""

    request: KeyRequestOut
    key: ProvisionedKeyOut | None
