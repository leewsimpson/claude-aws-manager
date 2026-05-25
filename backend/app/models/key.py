"""Provisioned Bedrock API key metadata model.

Bearer tokens are never stored — there is deliberately no token column.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy import TIMESTAMP
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models._mixins import TimestampMixin
from app.models.key_request import KeyRequest


class Key(Base, TimestampMixin):
    """One provisioned key, backed by a dedicated IAM user."""

    __tablename__ = "keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    developer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    cost_centre_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cost_centres.id"), nullable=False
    )
    key_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("key_requests.id"),
        unique=True,
        nullable=False,
    )
    iam_username: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    # NULL while the key is 'ready' (identity provisioned, credential not yet issued).
    # Set when the developer retrieves the token. Postgres allows multiple NULLs
    # under the unique constraint.
    credential_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )
    allowed_models: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), nullable=False
    )
    rolling_limit: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    rolling_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lifetime_budget: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    lifetime_spend: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0.00")
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    # When the developer first retrieved (claimed) the bearer token. NULL while 'ready'.
    token_retrieved_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    key_request: Mapped[KeyRequest] = relationship()

    __table_args__ = (
        Index("idx_keys_developer", "developer_id"),
        Index("idx_keys_cost_centre", "cost_centre_id"),
        Index("idx_keys_status", "status"),
        Index(
            "uq_keys_active_dev_cc",
            "developer_id",
            "cost_centre_id",
            unique=True,
            postgresql_where=text("status IN ('active', 'stopped', 'ready')"),
        ),
    )
