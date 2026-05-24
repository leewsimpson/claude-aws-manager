# Backend image — FastAPI served by uvicorn, deps managed by uv.
# Build context is ../backend (set in docker-compose.yml).
FROM python:3.12-slim

# uv: fast Python package manager (copied from the official distroless image).
COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install dependencies first (cached layer) using only the lockfile + manifest.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy the application source and install the project itself.
COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000

# docker-compose runs `alembic upgrade head && python -m app.seed` before
# uvicorn (see the compose `command`). This bare CMD is the fallback for
# running the image directly; it does not migrate/seed.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
