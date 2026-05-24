"""SQLAlchemy declarative base.

All ORM models (added in Phase 2) inherit from ``Base``. Alembic reads
``Base.metadata`` as its ``target_metadata`` for autogeneration.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
