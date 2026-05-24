"""Reusable audit-log primitive.

``record_audit`` constructs an :class:`~app.models.audit_log.AuditLog` row and
adds it to the session — the calling request handler is responsible for the
commit. This is the first audit writer; later phases reuse it for keys,
requests, settings, etc.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def _jsonable(value: Any) -> Any:
    """Coerce a value into something JSON-serialisable for JSONB storage."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def record_audit(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    old_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Append an audit row to ``db`` (no commit — the handler commits)."""
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_values=_jsonable(old_values) if old_values is not None else None,
            new_values=_jsonable(new_values) if new_values is not None else None,
            ip_address=ip_address,
        )
    )
