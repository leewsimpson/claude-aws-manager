"""Shared test fixtures: a real Postgres test DB with per-test rollback.

The test DB URL is derived from ``settings.database_url`` by swapping the
database name to ``claudeaws_test``; it is created on first use against the
maintenance ``postgres`` database.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, make_url, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.seed import seed

TEST_DB_NAME = "claudeaws_test"


def _test_db_url() -> str:
    url = make_url(get_settings().database_url)
    return url.set(database=TEST_DB_NAME).render_as_string(hide_password=False)


def _ensure_test_database() -> None:
    """Create the test database if it does not already exist."""
    admin_url = make_url(get_settings().database_url).set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"),
            {"n": TEST_DB_NAME},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin_engine.dispose()


@pytest.fixture(scope="session")
def engine() -> Generator[Engine, None, None]:
    _ensure_test_database()
    eng = create_engine(_test_db_url(), pool_pre_ping=True)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(engine: Engine) -> Generator[Session, None, None]:
    """Per-test session bound to a connection that is rolled back afterwards.

    Uses a SAVEPOINT that is restarted on each ``commit()`` so that the seed
    fixture (which commits) stays isolated within the outer transaction.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, autoflush=False, autocommit=False)()
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess: Session, trans: object) -> None:
        if trans.nested and not trans._parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def seeded(db_session: Session) -> Session:
    """A session with the hard-coded PoC users + settings seeded in."""
    seed(db_session)
    return db_session


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient whose ``get_db`` dependency yields the per-test session."""

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
