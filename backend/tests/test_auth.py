"""L3 integration tests for the auth endpoints (real Postgres + TestClient)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_login_success(client: TestClient, seeded: Session) -> None:
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["username"] == "admin"
    assert body["user"]["roles"] == ["admin"]
    assert "id" in body["user"] and "email" in body["user"]


def test_login_wrong_password(client: TestClient, seeded: Session) -> None:
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "nope"}
    )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid username or password"}


def test_login_unknown_user(client: TestClient, seeded: Session) -> None:
    resp = client.post(
        "/api/auth/login", json={"username": "ghost", "password": "x"}
    )
    assert resp.status_code == 401


def test_me_with_token(client: TestClient, seeded: Session) -> None:
    login = client.post(
        "/api/auth/login", json={"username": "ccowner1", "password": "ccowner1"}
    )
    token = login.json()["access_token"]
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "ccowner1"
    assert body["is_active"] is True
    assert set(body["roles"]) == {"cco", "developer"}


def test_me_without_token(client: TestClient, seeded: Session) -> None:
    resp = client.get("/api/auth/me")
    assert resp.status_code in (401, 403)


def test_me_garbage_token(client: TestClient, seeded: Session) -> None:
    resp = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert resp.status_code == 401
