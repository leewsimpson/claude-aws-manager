"""Tests for the /api/health endpoint.

The DB dependency is overridden with a hermetic stub so the test runs without
a real database.
"""

from collections.abc import Generator

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


class _StubSession:
    """Minimal stand-in for a SQLAlchemy Session whose execute() succeeds."""

    def execute(self, *_args: object, **_kwargs: object) -> object:
        return True

    def close(self) -> None:
        pass


class _FailingSession(_StubSession):
    """Stub whose execute() raises, simulating a DB outage."""

    def execute(self, *_args: object, **_kwargs: object) -> object:
        raise RuntimeError("database unavailable")


def _override_with(session: _StubSession):
    def _get_db() -> Generator[_StubSession, None, None]:
        try:
            yield session
        finally:
            session.close()

    return _get_db


def test_health_ok() -> None:
    app.dependency_overrides[get_db] = _override_with(_StubSession())
    try:
        client = TestClient(app)
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "ok"}
    finally:
        app.dependency_overrides.clear()


def test_health_database_error() -> None:
    app.dependency_overrides[get_db] = _override_with(_FailingSession())
    try:
        client = TestClient(app)
        response = client.get("/api/health")
        assert response.status_code == 503
        assert response.json() == {"status": "ok", "database": "error"}
    finally:
        app.dependency_overrides.clear()
