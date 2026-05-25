"""L3 integration tests for Phase 6 key management & developer dashboard."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.cost_centre import CostCentre
from app.models.cost_centre_owner import CostCentreOwner
from app.models.key import Key
from app.models.user import User
from app.services.aws import MockAwsService, get_aws_service
from app.main import app


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_key_requests.py)
# ---------------------------------------------------------------------------


def _token(client: TestClient, username: str) -> str:
    resp = client.post(
        "/api/auth/login", json={"username": username, "password": username}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_cc(client: TestClient, token: str, code: str = "CC-TEST", **overrides) -> dict:
    body = {"code": code, "name": f"Test CC {code}"}
    body.update(overrides)
    resp = client.post("/api/cost-centres", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _make_cco_of(db: Session, username: str, cc_id: str) -> None:
    """Directly insert a CostCentreOwner row and grant 'cco' role."""
    user = db.scalar(select(User).where(User.username == username))
    assert user is not None
    admin = db.scalar(select(User).where(User.username == "admin"))
    if "cco" not in (user.roles or []):
        user.roles = [*(user.roles or []), "cco"]
    existing = db.scalar(
        select(CostCentreOwner).where(
            CostCentreOwner.user_id == user.id,
            CostCentreOwner.cost_centre_id == cc_id,
        )
    )
    if existing is None:
        db.add(
            CostCentreOwner(
                cost_centre_id=cc_id,
                user_id=user.id,
                assigned_by=admin.id,
            )
        )
    db.flush()


def _provision_key(
    client: TestClient,
    db: Session,
    *,
    developer_username: str,
    cc_id: str,
    admin_token: str | None = None,
) -> dict:
    """Drive the real request → approve → developer-retrieve flow.

    Approval provisions a 'ready' key (no token in the response); the developer then
    retrieves the bearer token. Returns the retrieve response (an active
    ProvisionedKeyOut with ``bearer_token``).
    """
    dev_token = _token(client, developer_username)

    if admin_token is None:
        admin_token = _token(client, "admin")

    req_resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc_id},
        headers=_auth(dev_token),
    )
    assert req_resp.status_code == 201, req_resp.text
    request_id = req_resp.json()["request"]["id"]

    approve_resp = client.post(
        f"/api/key-requests/{request_id}/approve",
        json={},
        headers=_auth(admin_token),
    )
    assert approve_resp.status_code == 200, approve_resp.text
    # The approver never sees the token.
    assert approve_resp.json()["key"] is None

    ready = next(
        k
        for k in client.get("/api/keys", headers=_auth(dev_token)).json()
        if k["cost_centre_id"] == cc_id and k["status"] == "ready"
    )
    retrieve_resp = client.post(
        f"/api/keys/{ready['id']}/retrieve", headers=_auth(dev_token)
    )
    assert retrieve_resp.status_code == 200, retrieve_resp.text
    return retrieve_resp.json()


@pytest.fixture(autouse=True)
def _fresh_aws():
    """Replace the lru_cache singleton with a fresh MockAwsService per test."""
    mock = MockAwsService()
    app.dependency_overrides[get_aws_service] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_aws_service, None)


# ---------------------------------------------------------------------------
# GET /keys — scoping
# ---------------------------------------------------------------------------


def test_developer_sees_only_own_keys(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc1 = _create_cc(client, admin, code="KS-SC1")
    cc2 = _create_cc(client, admin, code="KS-SC2")

    _provision_key(client, seeded, developer_username="dev1", cc_id=cc1["id"], admin_token=admin)
    _provision_key(client, seeded, developer_username="dev2", cc_id=cc2["id"], admin_token=admin)

    dev1_token = _token(client, "dev1")
    resp = client.get("/api/keys", headers=_auth(dev1_token))
    assert resp.status_code == 200
    usernames = {k["developer_username"] for k in resp.json()}
    assert usernames == {"dev1"}


def test_cco_sees_their_cc_keys_not_others(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc1 = _create_cc(client, admin, code="KS-CCO1")
    cc2 = _create_cc(client, admin, code="KS-CCO2")

    _make_cco_of(seeded, "ccowner1", cc1["id"])
    seeded.commit()

    _provision_key(client, seeded, developer_username="dev1", cc_id=cc1["id"], admin_token=admin)
    _provision_key(client, seeded, developer_username="dev2", cc_id=cc2["id"], admin_token=admin)

    cco_token = _token(client, "ccowner1")
    resp = client.get("/api/keys", headers=_auth(cco_token))
    assert resp.status_code == 200
    cc_codes = {k["cost_centre_code"] for k in resp.json()}
    assert "KS-CCO1" in cc_codes
    assert "KS-CCO2" not in cc_codes


def test_admin_sees_all_keys(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc1 = _create_cc(client, admin, code="KS-ADM1")
    cc2 = _create_cc(client, admin, code="KS-ADM2")

    _provision_key(client, seeded, developer_username="dev1", cc_id=cc1["id"], admin_token=admin)
    _provision_key(client, seeded, developer_username="dev2", cc_id=cc2["id"], admin_token=admin)

    resp = client.get("/api/keys", headers=_auth(admin))
    assert resp.status_code == 200
    cc_codes = {k["cost_centre_code"] for k in resp.json()}
    assert {"KS-ADM1", "KS-ADM2"} <= cc_codes


def test_status_filter(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-SF1")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    resp_active = client.get("/api/keys?status=active", headers=_auth(admin))
    assert resp_active.status_code == 200
    statuses = {k["status"] for k in resp_active.json()}
    assert "active" in statuses

    # Revoke the key then filter by revoked
    dev1_token = _token(client, "dev1")
    client.post(f"/api/keys/{key_data['id']}/revoke", headers=_auth(dev1_token))

    resp_revoked = client.get("/api/keys?status=revoked", headers=_auth(admin))
    assert resp_revoked.status_code == 200
    assert all(k["status"] == "revoked" for k in resp_revoked.json())


def test_cost_centre_id_filter(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc1 = _create_cc(client, admin, code="KS-CF1")
    cc2 = _create_cc(client, admin, code="KS-CF2")

    _provision_key(client, seeded, developer_username="dev1", cc_id=cc1["id"], admin_token=admin)
    _provision_key(client, seeded, developer_username="dev2", cc_id=cc2["id"], admin_token=admin)

    resp = client.get(f"/api/keys?cost_centre_id={cc1['id']}", headers=_auth(admin))
    assert resp.status_code == 200
    assert all(k["cost_centre_id"] == cc1["id"] for k in resp.json())


def test_developer_id_filter(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc1 = _create_cc(client, admin, code="KS-DF1")
    cc2 = _create_cc(client, admin, code="KS-DF2")

    k1 = _provision_key(client, seeded, developer_username="dev1", cc_id=cc1["id"], admin_token=admin)
    _provision_key(client, seeded, developer_username="dev2", cc_id=cc2["id"], admin_token=admin)

    dev1_key = seeded.get(Key, k1["id"])
    dev1_id = str(dev1_key.developer_id)

    resp = client.get(f"/api/keys?developer_id={dev1_id}", headers=_auth(admin))
    assert resp.status_code == 200
    assert all(k["developer_username"] == "dev1" for k in resp.json())


# ---------------------------------------------------------------------------
# GET /keys — KeyOut shape
# ---------------------------------------------------------------------------


def test_key_out_has_no_bearer_token(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-BT1")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    dev1_token = _token(client, "dev1")
    resp = client.get(f"/api/keys/{key_data['id']}", headers=_auth(dev1_token))
    assert resp.status_code == 200
    assert "bearer_token" not in resp.json()


def test_key_out_includes_inference_profiles(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-IP1")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    dev1_token = _token(client, "dev1")
    resp = client.get(f"/api/keys/{key_data['id']}", headers=_auth(dev1_token))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["inference_profiles"]) >= 1
    for profile in body["inference_profiles"]:
        assert "model_id" in profile
        assert "profile_arn" in profile
        assert "profile_name" in profile


def test_get_key_404_for_nonexistent(client: TestClient, seeded: Session) -> None:
    dev1_token = _token(client, "dev1")
    fake_id = str(uuid.uuid4())
    resp = client.get(f"/api/keys/{fake_id}", headers=_auth(dev1_token))
    assert resp.status_code == 404


def test_get_key_404_for_other_developer(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-VIS1")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    dev2_token = _token(client, "dev2")
    resp = client.get(f"/api/keys/{key_data['id']}", headers=_auth(dev2_token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /keys/{key_id}/revoke
# ---------------------------------------------------------------------------


def test_developer_revokes_own_key(
    client: TestClient, seeded: Session, db_session: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RV1")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    dev1_token = _token(client, "dev1")
    resp = client.post(f"/api/keys/{key_data['id']}/revoke", headers=_auth(dev1_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "revoked"
    assert body["revoked_at"] is not None

    # Audit row written
    row = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "key.revoked",
            AuditLog.entity_id == key_data["id"],
        )
    )
    assert row is not None


def test_admin_revokes_any_key(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RV2")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    resp = client.post(f"/api/keys/{key_data['id']}/revoke", headers=_auth(admin))
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"


def test_cco_revokes_key_in_their_cc(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RV3")
    _make_cco_of(seeded, "ccowner1", cc["id"])
    seeded.commit()

    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    cco_token = _token(client, "ccowner1")
    resp = client.post(f"/api/keys/{key_data['id']}/revoke", headers=_auth(cco_token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"


def test_revoke_already_revoked_409(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RV4")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    dev1_token = _token(client, "dev1")
    client.post(f"/api/keys/{key_data['id']}/revoke", headers=_auth(dev1_token))

    resp = client.post(f"/api/keys/{key_data['id']}/revoke", headers=_auth(dev1_token))
    assert resp.status_code == 409


def test_different_developer_revoke_404(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RV5")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    dev2_token = _token(client, "dev2")
    resp = client.post(f"/api/keys/{key_data['id']}/revoke", headers=_auth(dev2_token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /keys/{key_id}/regenerate
# ---------------------------------------------------------------------------


def test_developer_regenerates_own_key(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RG1")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    dev1_token = _token(client, "dev1")
    resp = client.post(f"/api/keys/{key_data['id']}/regenerate", headers=_auth(dev1_token))
    assert resp.status_code == 200
    body = resp.json()
    assert "bearer_token" in body
    assert body["bearer_token"].startswith("br-")
    assert body["bearer_token"] != key_data["bearer_token"]


def test_regenerate_audit_written(
    client: TestClient, seeded: Session, db_session: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RG2")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    dev1_token = _token(client, "dev1")
    client.post(f"/api/keys/{key_data['id']}/regenerate", headers=_auth(dev1_token))

    row = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "key.regenerated",
            AuditLog.entity_id == key_data["id"],
        )
    )
    assert row is not None


def test_cco_not_owner_regenerate_403(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RG3")
    _make_cco_of(seeded, "ccowner1", cc["id"])
    seeded.commit()

    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    cco_token = _token(client, "ccowner1")
    resp = client.post(f"/api/keys/{key_data['id']}/regenerate", headers=_auth(cco_token))
    assert resp.status_code == 403


def test_different_dev_regenerate_404(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RG4")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    dev2_token = _token(client, "dev2")
    resp = client.post(f"/api/keys/{key_data['id']}/regenerate", headers=_auth(dev2_token))
    assert resp.status_code == 404


def test_regenerate_revoked_key_409(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RG5")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    dev1_token = _token(client, "dev1")
    client.post(f"/api/keys/{key_data['id']}/revoke", headers=_auth(dev1_token))

    resp = client.post(f"/api/keys/{key_data['id']}/regenerate", headers=_auth(dev1_token))
    assert resp.status_code == 409


def test_admin_regenerates_any_key(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RG6")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    resp = client.post(f"/api/keys/{key_data['id']}/regenerate", headers=_auth(admin))
    assert resp.status_code == 200
    assert resp.json()["bearer_token"].startswith("br-")


# ---------------------------------------------------------------------------
# POST /keys/{key_id}/retrieve — developer claims the deferred credential
# ---------------------------------------------------------------------------


def _approve_to_ready(
    client: TestClient, *, developer_username: str, cc_id: str, admin_token: str
) -> tuple[str, dict]:
    """Drive request → approve so the dev has a 'ready' key. Return (dev_token, ready_key)."""
    dev_token = _token(client, developer_username)
    req = client.post(
        "/api/key-requests", json={"cost_centre_id": cc_id}, headers=_auth(dev_token)
    )
    request_id = req.json()["request"]["id"]
    approve = client.post(
        f"/api/key-requests/{request_id}/approve", json={}, headers=_auth(admin_token)
    )
    assert approve.status_code == 200
    assert approve.json()["key"] is None  # approver never sees the token
    ready = next(
        k
        for k in client.get("/api/keys", headers=_auth(dev_token)).json()
        if k["cost_centre_id"] == cc_id and k["status"] == "ready"
    )
    assert ready["status"] == "ready"
    assert ready["token_retrieved_at"] is None
    return dev_token, ready


def test_developer_retrieves_ready_key(
    client: TestClient, seeded: Session, db_session: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RT1")
    dev_token, ready = _approve_to_ready(
        client, developer_username="dev1", cc_id=cc["id"], admin_token=admin
    )

    resp = client.post(f"/api/keys/{ready['id']}/retrieve", headers=_auth(dev_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["bearer_token"].startswith("br-")
    assert body["status"] == "active"

    # The key is now active with a retrieval timestamp, visible to the dev.
    after = client.get(f"/api/keys/{ready['id']}", headers=_auth(dev_token)).json()
    assert after["status"] == "active"
    assert after["token_retrieved_at"] is not None

    # Audit row written for the claim.
    row = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "key.token_retrieved",
            AuditLog.entity_id == ready["id"],
        )
    )
    assert row is not None


def test_cco_cannot_retrieve_token_403(client: TestClient, seeded: Session) -> None:
    """A CCO who can see the key but isn't the developer-owner cannot retrieve it."""
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RT2")
    _make_cco_of(seeded, "ccowner1", cc["id"])
    seeded.commit()

    _, ready = _approve_to_ready(
        client, developer_username="dev1", cc_id=cc["id"], admin_token=admin
    )

    cco_token = _token(client, "ccowner1")
    resp = client.post(f"/api/keys/{ready['id']}/retrieve", headers=_auth(cco_token))
    assert resp.status_code == 403


def test_other_developer_retrieve_404(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RT3")
    _, ready = _approve_to_ready(
        client, developer_username="dev1", cc_id=cc["id"], admin_token=admin
    )

    dev2_token = _token(client, "dev2")
    resp = client.post(f"/api/keys/{ready['id']}/retrieve", headers=_auth(dev2_token))
    assert resp.status_code == 404


def test_retrieve_active_key_409(client: TestClient, seeded: Session) -> None:
    """Once claimed (active), retrieve is rejected — regenerate is the path instead."""
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RT4")
    key_data = _provision_key(
        client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin
    )

    dev1_token = _token(client, "dev1")
    resp = client.post(f"/api/keys/{key_data['id']}/retrieve", headers=_auth(dev1_token))
    assert resp.status_code == 409


def test_admin_can_retrieve_ready_key(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-RT5")
    _, ready = _approve_to_ready(
        client, developer_username="dev1", cc_id=cc["id"], admin_token=admin
    )

    resp = client.post(f"/api/keys/{ready['id']}/retrieve", headers=_auth(admin))
    assert resp.status_code == 200
    assert resp.json()["bearer_token"].startswith("br-")


# ---------------------------------------------------------------------------
# PATCH /keys/{key_id}/constraints
# ---------------------------------------------------------------------------


def test_cco_updates_rolling_limit(
    client: TestClient, seeded: Session, db_session: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-CN1")
    _make_cco_of(seeded, "ccowner1", cc["id"])
    seeded.commit()

    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    cco_token = _token(client, "ccowner1")
    resp = client.patch(
        f"/api/keys/{key_data['id']}/constraints",
        json={"rolling_limit": 50.0, "rolling_period_days": 7},
        headers=_auth(cco_token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rolling_limit"] == 50.0
    assert body["rolling_period_days"] == 7

    # Audit row
    row = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "key.constraints_updated",
            AuditLog.entity_id == key_data["id"],
        )
    )
    assert row is not None


def test_cco_updates_expiry_days(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-CN2")
    _make_cco_of(seeded, "ccowner1", cc["id"])
    seeded.commit()

    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    cco_token = _token(client, "ccowner1")
    resp = client.patch(
        f"/api/keys/{key_data['id']}/constraints",
        json={"expiry_days": 60},
        headers=_auth(cco_token),
    )
    assert resp.status_code == 200
    assert resp.json()["expires_at"] is not None


def test_admin_updates_constraints(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-CN3")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    resp = client.patch(
        f"/api/keys/{key_data['id']}/constraints",
        json={"lifetime_budget": 100.0},
        headers=_auth(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["lifetime_budget"] == 100.0


def test_developer_patch_constraints_403(client: TestClient, seeded: Session) -> None:
    """Dev-owner who is not CCO/admin cannot update constraints."""
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-CN4")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    dev1_token = _token(client, "dev1")
    resp = client.patch(
        f"/api/keys/{key_data['id']}/constraints",
        json={"rolling_limit": 25.0},
        headers=_auth(dev1_token),
    )
    assert resp.status_code == 403


def test_invalid_model_in_constraints_400(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-CN5")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    resp = client.patch(
        f"/api/keys/{key_data['id']}/constraints",
        json={"allowed_models": ["anthropic.claude-not-a-real-model"]},
        headers=_auth(admin),
    )
    assert resp.status_code == 400
    assert "not in globally allowed set" in resp.json()["detail"]


def test_update_allowed_models_valid_subset(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-CN6")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    # Get current allowed_models from the provisioned key
    dev1_token = _token(client, "dev1")
    key_resp = client.get(f"/api/keys/{key_data['id']}", headers=_auth(dev1_token))
    current_models = key_resp.json()["allowed_models"]

    # Use a valid single-model subset
    subset = [current_models[0]]
    resp = client.patch(
        f"/api/keys/{key_data['id']}/constraints",
        json={"allowed_models": subset},
        headers=_auth(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["allowed_models"] == subset


def test_constraints_on_revoked_key_409(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-CN7")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    # Revoke first
    dev1_token = _token(client, "dev1")
    client.post(f"/api/keys/{key_data['id']}/revoke", headers=_auth(dev1_token))

    resp = client.patch(
        f"/api/keys/{key_data['id']}/constraints",
        json={"rolling_limit": 10.0},
        headers=_auth(admin),
    )
    assert resp.status_code == 409


def test_revoke_on_revoked_key_409(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KS-CN8")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    client.post(f"/api/keys/{key_data['id']}/revoke", headers=_auth(admin))
    resp = client.post(f"/api/keys/{key_data['id']}/revoke", headers=_auth(admin))
    assert resp.status_code == 409


def test_get_keys_list_ordered_by_created_at_desc(
    client: TestClient, seeded: Session
) -> None:
    admin = _token(client, "admin")
    cc1 = _create_cc(client, admin, code="KS-ORD1")
    cc2 = _create_cc(client, admin, code="KS-ORD2")

    _provision_key(client, seeded, developer_username="dev1", cc_id=cc1["id"], admin_token=admin)
    _provision_key(client, seeded, developer_username="dev2", cc_id=cc2["id"], admin_token=admin)

    resp = client.get("/api/keys", headers=_auth(admin))
    assert resp.status_code == 200
    items = resp.json()
    created_ats = [k["created_at"] for k in items]
    assert created_ats == sorted(created_ats, reverse=True)
