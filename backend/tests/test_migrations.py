"""Migration round-trip test: upgrade head → inspect tables → downgrade base.

Creates a throwaway database, runs alembic upgrade head from empty, asserts
all expected tables exist (including inference_profiles), then runs downgrade
base cleanly. The test does not depend on the main test DB schema.
"""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, make_url, text

from app.config import get_settings

_MIGRATE_DB_NAME = "claudeaws_migrate_test"

_EXPECTED_TABLES = {
    "users",
    "cost_centres",
    "cost_centre_owners",
    "key_requests",
    "keys",
    "audit_log",
    "global_settings",
    "inference_profiles",
}


def _migrate_db_url() -> str:
    url = make_url(get_settings().database_url)
    return url.set(database=_MIGRATE_DB_NAME).render_as_string(hide_password=False)


def _ensure_migrate_database() -> None:
    admin_url = make_url(get_settings().database_url).set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        # Drop + recreate for a guaranteed-empty starting point
        conn.execute(
            text(
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{_MIGRATE_DB_NAME}'"
            )
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{_MIGRATE_DB_NAME}"'))
        conn.execute(text(f'CREATE DATABASE "{_MIGRATE_DB_NAME}"'))
    admin_engine.dispose()


def _make_alembic_config(db_url: str) -> Config:
    """Build an Alembic Config pointing at the backend directory.

    env.py calls get_settings() and overwrites sqlalchemy.url from the
    DATABASE_URL env var. We set that env var so our throwaway DB URL wins.
    """
    import os
    os.environ["DATABASE_URL"] = db_url
    # Force pydantic-settings cache to reload with the new env var
    from app.config import get_settings as _gs
    _gs.cache_clear()

    backend_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    ini_path = os.path.join(backend_dir, "alembic.ini")
    cfg = Config(ini_path)
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
    return cfg


@pytest.mark.slow
def test_migration_round_trip() -> None:
    """Upgrade from empty to head, verify tables, then downgrade to base."""
    import os
    from app.config import get_settings as _get_settings

    db_url = _migrate_db_url()

    # Guard: if Postgres is unreachable, skip rather than fail hard.
    try:
        _ensure_migrate_database()
    except Exception as exc:
        pytest.skip(f"Cannot reach Postgres for migration test: {exc}")

    original_db_url = os.environ.get("DATABASE_URL")
    try:
        cfg = _make_alembic_config(db_url)

        # --- upgrade head ---------------------------------------------------
        command.upgrade(cfg, "head")

        engine = create_engine(db_url)
        with engine.connect():
            insp = inspect(engine)
            present = set(insp.get_table_names())
        engine.dispose()

        # alembic_version is created by Alembic itself — exclude it
        app_tables = present - {"alembic_version"}
        missing = _EXPECTED_TABLES - app_tables
        assert not missing, f"Tables missing after upgrade: {missing}"

        # --- downgrade base -------------------------------------------------
        command.downgrade(cfg, "base")

        engine = create_engine(db_url)
        with engine.connect():
            insp = inspect(engine)
            remaining = set(insp.get_table_names()) - {"alembic_version"}
        engine.dispose()

        assert not remaining, f"Tables still present after downgrade: {remaining}"

    finally:
        # Restore original settings cache
        if original_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_db_url
        _get_settings.cache_clear()

        # Best-effort cleanup of throwaway DB
        try:
            original_url = make_url(
                "postgresql+psycopg://claudeaws:claudeaws@localhost:5432/postgres"
            )
            # Use the original (pre-override) settings URL
            admin_engine = create_engine(
                original_url.render_as_string(hide_password=False),
                isolation_level="AUTOCOMMIT",
            )
            with admin_engine.connect() as conn:
                conn.execute(
                    text(
                        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        f"WHERE datname = '{_MIGRATE_DB_NAME}'"
                    )
                )
                conn.execute(text(f'DROP DATABASE IF EXISTS "{_MIGRATE_DB_NAME}"'))
            admin_engine.dispose()
        except Exception:
            pass
