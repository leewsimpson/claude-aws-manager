"""Health-check endpoint.

Mounted under the ``/api`` prefix in ``app.main`` → ``GET /api/health``.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> JSONResponse:
    """Liveness/readiness probe.

    Executes ``SELECT 1`` against the database. Returns 200 with
    ``database: "ok"`` on success, or 503 with ``database: "error"`` if the
    query fails.
    """
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "ok", "database": "error"},
        )
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "database": "ok"},
    )
