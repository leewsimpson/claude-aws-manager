"""Inference profile model.

One row per (cost_centre, model) pair. Created on first approval for that
combination; the partial unique index on (cost_centre_id, model_id) WHERE
status = 'active' enforces the one-active-profile-per-CC-model invariant.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InferenceProfile(Base):
    """AWS Application Inference Profile created by the platform."""

    __tablename__ = "inference_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    cost_centre_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cost_centres.id"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    profile_arn: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    profile_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index(
            "uq_inference_profiles_cc_model",
            "cost_centre_id",
            "model_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )
