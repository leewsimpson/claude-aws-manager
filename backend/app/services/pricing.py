"""Pricing service: constants, cost computation, and pricing-cache helpers.

All prices are USD per 1,000 tokens. The ``PRICING`` constant is the
hard-coded PoC seed; ``load_pricing`` reads live ``pricing_cache`` rows
(falling back to the constant for any missing model).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TypedDict

from sqlalchemy.orm import Session

from app.models.pricing_cache import PricingCache
from app.services.aws.base import TokenUsage

# ---------------------------------------------------------------------------
# Pricing constants (USD per 1,000 tokens)
# ---------------------------------------------------------------------------


class _Prices(TypedDict):
    model_name: str
    input_price_per_1k: float
    output_price_per_1k: float
    cache_read_price_per_1k: float | None
    cache_write_price_per_1k: float | None


PRICING: dict[str, _Prices] = {
    "anthropic.claude-sonnet-4-6": {
        "model_name": "Claude Sonnet 4.6",
        "input_price_per_1k": 0.003,
        "output_price_per_1k": 0.015,
        "cache_read_price_per_1k": 0.0003,
        "cache_write_price_per_1k": 0.00375,
    },
    "anthropic.claude-haiku-4-5": {
        "model_name": "Claude Haiku 4.5",
        "input_price_per_1k": 0.001,
        "output_price_per_1k": 0.005,
        "cache_read_price_per_1k": 0.0001,
        "cache_write_price_per_1k": 0.00125,
    },
    "anthropic.claude-opus-4-1": {
        "model_name": "Claude Opus 4.1",
        "input_price_per_1k": 0.015,
        "output_price_per_1k": 0.075,
        "cache_read_price_per_1k": 0.0015,
        "cache_write_price_per_1k": 0.01875,
    },
}

# ---------------------------------------------------------------------------
# Cost computation
# ---------------------------------------------------------------------------


def compute_cost(usage: TokenUsage, prices: _Prices | None) -> Decimal:
    """Return the dollar cost for ``usage`` given a ``prices`` dict.

    Missing or None ``prices`` → Decimal("0"). Missing cache prices → 0.
    """
    if prices is None:
        return Decimal("0")
    result = (
        Decimal(str(usage.input_tokens)) / 1000 * Decimal(str(prices["input_price_per_1k"]))
        + Decimal(str(usage.output_tokens)) / 1000 * Decimal(str(prices["output_price_per_1k"]))
    )
    cr = prices.get("cache_read_price_per_1k")
    cw = prices.get("cache_write_price_per_1k")
    if cr is not None:
        result += Decimal(str(usage.cache_read_tokens)) / 1000 * Decimal(str(cr))
    if cw is not None:
        result += Decimal(str(usage.cache_write_tokens)) / 1000 * Decimal(str(cw))
    return result

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def seed_pricing(db: Session) -> None:
    """Idempotent upsert of ``PRICING`` into ``pricing_cache`` (region ap-southeast-2).

    ``expires_at`` is set to now + 1 day. Safe to run on every startup.
    """
    from sqlalchemy import select

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=1)
    for model_id, prices in PRICING.items():
        row = db.scalar(
            select(PricingCache).where(PricingCache.model_id == model_id)
        )
        if row is None:
            db.add(
                PricingCache(
                    model_id=model_id,
                    model_name=prices["model_name"],
                    input_price_per_1k=prices["input_price_per_1k"],
                    output_price_per_1k=prices["output_price_per_1k"],
                    cache_read_price_per_1k=prices.get("cache_read_price_per_1k"),
                    cache_write_price_per_1k=prices.get("cache_write_price_per_1k"),
                    region="ap-southeast-2",
                    fetched_at=now,
                    expires_at=expires_at,
                )
            )
        else:
            row.model_name = prices["model_name"]
            row.input_price_per_1k = prices["input_price_per_1k"]
            row.output_price_per_1k = prices["output_price_per_1k"]
            row.cache_read_price_per_1k = prices.get("cache_read_price_per_1k")
            row.cache_write_price_per_1k = prices.get("cache_write_price_per_1k")
            row.fetched_at = now
            row.expires_at = expires_at


def load_pricing(db: Session) -> dict[str, _Prices]:
    """Load pricing from ``pricing_cache``, falling back to ``PRICING`` for missing models.

    Returns a dict mapping model_id to price data in the same shape as ``PRICING``.
    Cost for an unknown model → the key will be absent → callers should use
    ``pricing.get(model_id)`` and pass ``None``-safe to ``compute_cost``.
    """
    from sqlalchemy import select
    rows = db.scalars(select(PricingCache)).all()
    result: dict[str, _Prices] = {}
    for row in rows:
        result[row.model_id] = {
            "model_name": row.model_name or row.model_id,
            "input_price_per_1k": float(row.input_price_per_1k),
            "output_price_per_1k": float(row.output_price_per_1k),
            "cache_read_price_per_1k": float(row.cache_read_price_per_1k) if row.cache_read_price_per_1k is not None else None,
            "cache_write_price_per_1k": float(row.cache_write_price_per_1k) if row.cache_write_price_per_1k is not None else None,
        }
    # Fall back to PRICING for any model not in the DB
    for model_id, prices in PRICING.items():
        if model_id not in result:
            result[model_id] = prices
    return result
