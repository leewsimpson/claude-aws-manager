"""Usage snapshot model.

Periodic token usage and cost data collected by the background scheduler.
Two data paths feed this table:
1. CloudWatch metrics — CC-level totals per inference profile (key_id NULL).
2. Model invocation logs — per-key breakdown (key_id populated).
"""

import uuid
from datetime import datetime

from sqlalchemy import BIGINT, ForeignKey, Index, Numeric, String, text
from sqlalchemy import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UsageSnapshot(Base):
    """A single poll-cycle snapshot of token usage from one source."""

    __tablename__ = "usage_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("keys.id"), nullable=True
    )
    inference_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inference_profiles.id"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'cloudwatch'")
    )
    input_tokens: Mapped[int] = mapped_column(
        BIGINT, nullable=False, server_default=text("0")
    )
    output_tokens: Mapped[int] = mapped_column(
        BIGINT, nullable=False, server_default=text("0")
    )
    cache_read_tokens: Mapped[int] = mapped_column(
        BIGINT, nullable=False, server_default=text("0")
    )
    cache_write_tokens: Mapped[int] = mapped_column(
        BIGINT, nullable=False, server_default=text("0")
    )
    cost: Mapped[float] = mapped_column(
        Numeric(12, 4), nullable=False, server_default=text("0.0000")
    )
    period_start: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("idx_usage_key_period", "key_id", "period_start"),
        Index("idx_usage_profile_period", "inference_profile_id", "period_start"),
        Index("idx_usage_collected_at", "collected_at"),
    )
