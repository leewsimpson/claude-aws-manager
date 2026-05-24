# Backend — Claude Code AWS Bedrock Manager

Python + FastAPI service that provisions and governs Claude Code access via AWS Bedrock.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (package manager)
- Python 3.12 (uv will fetch it automatically — pinned via `.python-version`)
- A PostgreSQL database for the `/api/health` check and migrations

## Run locally

```powershell
uv sync                                   # create the venv + install deps (writes uv.lock)
uv run uvicorn app.main:app --reload      # serve on http://localhost:8000
```

The server binds to `0.0.0.0:8000` under Docker (see `/docker`); `--reload` is for local dev.

Health check: `GET http://localhost:8000/api/health` → `{"status":"ok","database":"ok"}`.

## Run tests

```powershell
uv run pytest -q
```

## Configuration

Settings are read from environment variables via `pydantic-settings` (see `app/config.py`):

| Env var        | Default                                                              | Purpose                          |
|----------------|----------------------------------------------------------------------|----------------------------------|
| `DATABASE_URL` | `postgresql+psycopg://claudeaws:claudeaws@localhost:5432/claudeaws`  | SQLAlchemy URL (psycopg v3)      |
| `AWS_MODE`     | `mock`                                                               | `mock` or `real` AWS integration |
| `CORS_ORIGINS` | `http://localhost:5173`                                              | Comma-separated allowed origins  |

## Database migrations (Alembic)

```powershell
uv run alembic upgrade head           # apply migrations
uv run alembic revision -m "message"  # create a new migration (Phase 2+)
```

Alembic reads `DATABASE_URL` from the same settings; no schema/tables exist yet (Phase 1).
