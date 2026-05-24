"""L1 unit tests for password hashing and JWT helpers (no DB)."""

import uuid

import jwt
import pytest
from freezegun import freeze_time

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_round_trip() -> None:
    hashed = hash_password("s3cret")
    assert hashed != "s3cret"
    assert verify_password("s3cret", hashed)


def test_password_wrong_fails() -> None:
    hashed = hash_password("s3cret")
    assert not verify_password("wrong", hashed)


def test_jwt_round_trip() -> None:
    user_id = str(uuid.uuid4())
    token = create_access_token(user_id)
    payload = decode_access_token(token)
    assert payload["sub"] == user_id
    assert "exp" in payload


def test_jwt_expired_rejected() -> None:
    with freeze_time("2026-01-01 00:00:00"):
        token = create_access_token(str(uuid.uuid4()))
    # 480 min default expiry → advance well beyond it.
    with freeze_time("2026-01-02 00:00:00"):
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_access_token(token)


def test_jwt_tampered_rejected() -> None:
    token = create_access_token(str(uuid.uuid4()))
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token + "tampered")


def test_jwt_garbage_rejected() -> None:
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token("not-a-jwt")
