"""Pydantic response schemas for usage and cost-tracking endpoints (Phase 7)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class UsageSnapshotOut(BaseModel):
    """A single usage snapshot row (invocation_log source, for per-key drill-down)."""

    period_start: datetime
    period_end: datetime
    model_id: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost: float


class KeyUsageOut(BaseModel):
    """Usage detail for a single key."""

    key_id: uuid.UUID
    status: str
    rolling_limit: float | None
    rolling_period_days: int | None
    rolling_spend: float
    lifetime_budget: float | None
    lifetime_spend: float
    snapshots: list[UsageSnapshotOut]


class CcKeyUsageSummary(BaseModel):
    """Per-key summary within a cost-centre usage response."""

    key_id: uuid.UUID
    developer_username: str
    status: str
    lifetime_spend: float
    rolling_spend: float
    rolling_limit: float | None
    lifetime_budget: float | None


class ModelUsageSummary(BaseModel):
    """Usage broken down by model."""

    model_id: str
    cost: float
    total_tokens: int


class CcUsageOut(BaseModel):
    """Usage summary for a cost centre."""

    cost_centre_id: uuid.UUID
    cost_centre_code: str
    budget_cap: float | None
    total_spend: float
    keys: list[CcKeyUsageSummary]
    by_model: list[ModelUsageSummary]


class CcUsageSummaryItem(BaseModel):
    """Per-cost-centre row in the admin usage summary."""

    cost_centre_id: uuid.UUID
    code: str
    name: str
    budget_cap: float | None
    total_spend: float
    active_keys: int
    stopped_keys: int


class UsageSummaryOut(BaseModel):
    """Platform-wide usage summary (admin only)."""

    total_spend: float
    active_keys: int
    stopped_keys: int
    cost_centres: list[CcUsageSummaryItem]
    by_model: list[ModelUsageSummary]
