"""Pricing cache model.

Cached model pricing from the AWS Price List API. Refreshed daily by the
background scheduler. Hard-coded seed values for PoC.

All prices are stored as USD per 1,000 tokens.
"""

import uuid
from datetime import datetime

from sqlalchemy import Numeric, String, text
from sqlalchemy import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PricingCache(Base):
    """Cached per-model pricing, refreshed by the background scheduler."""

    __tablename__ = "pricing_cache"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    model_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_price_per_1k: Mapped[float] = mapped_column(
        Numeric(10, 6), nullable=False
    )
    output_price_per_1k: Mapped[float] = mapped_column(
        Numeric(10, 6), nullable=False
    )
    cache_read_price_per_1k: Mapped[float | None] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    cache_write_price_per_1k: Mapped[float | None] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    region: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'ap-southeast-2'")
    )
    fetched_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
