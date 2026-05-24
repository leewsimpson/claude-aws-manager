"""FastAPI application entry point.

Run locally with::

    uv run uvicorn app.main:app --reload

In containers it is served on ``0.0.0.0:8000``.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, cost_centres, health, key_requests, users
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="Claude Code AWS Bedrock Manager",
    description=(
        "Self-service provisioning and governance of Claude Code access "
        "via AWS Bedrock."
    ),
    version="0.1.0",
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
app.include_router(users.router, prefix="/api")
