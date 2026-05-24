"""L1 unit tests for the require_roles dependency logic (no DB)."""

import pytest
from fastapi import HTTPException

from app.core.deps import require_roles
from app.models.user import User


def _user(roles: list[str]) -> User:
    return User(username="u", display_name="U", email="u@e.com", roles=roles)


def test_matching_role_passes() -> None:
    dep = require_roles("admin")
    result = dep(user=_user(["admin", "developer"]))
    assert result.roles == ["admin", "developer"]


def test_any_of_several_roles_passes() -> None:
    dep = require_roles("admin", "cco")
    result = dep(user=_user(["cco"]))
    assert result.roles == ["cco"]


def test_missing_role_raises_403() -> None:
    dep = require_roles("admin")
    with pytest.raises(HTTPException) as exc:
        dep(user=_user(["developer"]))
    assert exc.value.status_code == 403
