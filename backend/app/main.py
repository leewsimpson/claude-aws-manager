"""FastAPI application entry point.

Run locally with::

    uv run uvicorn app.main:app --reload

In containers it is served on ``0.0.0.0:8000``.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, cost_centres, health, key_requests, keys, usage, users
from app.config import get_settings
from app.db.session import SessionLocal
from app.services.aws import get_aws_service
from app.services.usage_poller import UsagePoller, rehydrate_aws_from_db

settings = get_settings()

_poller: UsagePoller | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup: rehydrate mock AWS state + start poller. Shutdown: stop poller."""
    global _poller
    aws = get_aws_service()
    db = SessionLocal()
    try:
        rehydrate_aws_from_db(db, aws)
    finally:
        db.close()

    if settings.poller_enabled:
        _poller = UsagePoller(
            aws=aws,
            interval_seconds=settings.poll_interval_seconds,
        )
        _poller.start()

    yield

    if _poller is not None:
        _poller.stop()
        _poller = None


app = FastAPI(
    title="Claude Code AWS Bedrock Manager",
    description=(
        "Self-service provisioning and governance of Claude Code access "
        "via AWS Bedrock."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(cost_centres.router, prefix="/api")
app.include_router(key_requests.router, prefix="/api")
app.include_router(keys.router, prefix="/api")
app.include_router(usage.router, prefix="/api")
app.include_router(users.router, prefix="/api")
