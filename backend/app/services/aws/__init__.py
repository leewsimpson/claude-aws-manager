"""AWS service-layer package: interface, mock, real stub and the factory.

App code obtains the service via :func:`get_aws_service` (a process-wide singleton
so the in-memory mock state persists across requests). Tests construct
:class:`MockAwsService` directly (with an injected clock) for isolation.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.aws.base import (
    AwsService,
    AwsServiceError,
    DuplicateKeyError,
    DuplicateProfileError,
    InferenceProfileRef,
    KeyNotFoundError,
    KeyUsage,
    ProfileNotFoundError,
    ProvisionedKey,
    TokenUsage,
    build_model_policy,
)
from app.services.aws.mock import MockAwsService
from app.services.aws.real import RealAwsService

__all__ = [
    "AwsService",
    "AwsServiceError",
    "DuplicateKeyError",
    "DuplicateProfileError",
    "InferenceProfileRef",
    "KeyNotFoundError",
    "KeyUsage",
    "ProfileNotFoundError",
    "ProvisionedKey",
    "TokenUsage",
    "build_model_policy",
    "MockAwsService",
    "RealAwsService",
    "get_aws_service",
]


def _build(mode: str) -> AwsService:
    """Construct the service for the given ``AWS_MODE``."""
    if mode == "mock":
        return MockAwsService()
    if mode == "real":
        return RealAwsService()
    raise ValueError(f"Unknown AWS_MODE: {mode!r} (expected 'mock' or 'real')")


@lru_cache(maxsize=1)
def get_aws_service() -> AwsService:
    """Return the process-wide AWS service singleton.

    The singleton keeps the in-memory mock state alive across requests. Usable
    directly as a FastAPI dependency (Phase 5 will ``Depends()`` on it).
    """
    return _build(get_settings().aws_mode)
