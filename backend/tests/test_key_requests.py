"""L3 integration tests for Phase 5 key request & approval workflow."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.cost_centre import CostCentre
from app.models.cost_centre_owner import CostCentreOwner
from app.models.inference_profile import InferenceProfile
from app.models.key import Key
from app.models.key_request import KeyRequest
from app.models.user import User
from app.services.aws import AwsServiceError, MockAwsService, get_aws_service
from app.main import app


# ---------------------------------------------------------------------------
# Helpers (mirror the pattern from test_cost_centres.py)
# ---------------------------------------------------------------------------


def _token(client: TestClient, username: str) -> str:
    resp = client.post(
        "/api/auth/login", json={"username": username, "password": username}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _user_id(db: Session, username: str) -> str:
    user = db.scalar(select(User).where(User.username == username))
    assert user is not None
    return str(user.id)


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
    # Add cco role if not already present
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


@pytest.fixture(autouse=True)
def _fresh_aws():
    """Replace the lru_cache singleton with a fresh MockAwsService per test."""
    mock = MockAwsService()
    app.dependency_overrides[get_aws_service] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_aws_service, None)


# ---------------------------------------------------------------------------
# POST /key-requests — create
# ---------------------------------------------------------------------------


def test_developer_creates_pending_request(
    client: TestClient, seeded: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-PR01")
    dev = _token(client, "dev1")

    resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"], "justification": "Need for project"},
        headers=_auth(dev),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["request"]["status"] == "pending"
    assert body["key"] is None
    assert body["request"]["cost_centre_code"] == "CC-PR01"
    assert body["request"]["developer_username"] == "dev1"


def test_cco_auto_approval_returns_key_and_bearer_token(
    client: TestClient, seeded: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-AUTO")
    _make_cco_of(seeded, "ccowner1", cc["id"])
    seeded.commit()

    cco = _token(client, "ccowner1")
    resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(cco),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["request"]["status"] == "approved"
    assert body["key"] is not None
    assert body["key"]["bearer_token"].startswith("br-")
    assert body["key"]["status"] == "active"
    assert len(body["key"]["inference_profiles"]) > 0


def test_cco_auto_approval_creates_inference_profiles(
    client: TestClient, seeded: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-IP01")
    _make_cco_of(seeded, "ccowner1", cc["id"])
    seeded.commit()

    cco = _token(client, "ccowner1")
    resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(cco),
    )
    assert resp.status_code == 201, resp.text
    key_data = resp.json()["key"]
    # Should have a profile for each allowed model
    assert len(key_data["inference_profiles"]) >= 1
    for profile in key_data["inference_profiles"]:
        assert "profile_arn" in profile
        assert "model_id" in profile


def test_admin_approve_with_constraint_overrides(
    client: TestClient, seeded: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-OVR")
    dev = _token(client, "dev1")

    req_resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev),
    )
    assert req_resp.status_code == 201
    request_id = req_resp.json()["request"]["id"]

    approve_resp = client.post(
        f"/api/key-requests/{request_id}/approve",
        json={
            "allowed_models": ["anthropic.claude-haiku-4-5"],
            "rolling_limit": 25.0,
            "rolling_period_days": 14,
            "expiry_days": 30,
        },
        headers=_auth(admin),
    )
    assert approve_resp.status_code == 200, approve_resp.text
    body = approve_resp.json()
    assert body["request"]["status"] == "approved"
    assert body["key"] is not None
    key = body["key"]
    assert key["allowed_models"] == ["anthropic.claude-haiku-4-5"]
    assert key["rolling_limit"] == 25.0
    assert key["rolling_period_days"] == 14


def test_approve_validates_allowed_models_subset(
    client: TestClient, seeded: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-MOD")
    dev = _token(client, "dev1")

    req_resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev),
    )
    request_id = req_resp.json()["request"]["id"]

    resp = client.post(
        f"/api/key-requests/{request_id}/approve",
        json={"allowed_models": ["anthropic.claude-not-a-model"]},
        headers=_auth(admin),
    )
    assert resp.status_code == 400
    assert "not in globally allowed set" in resp.json()["detail"]


def test_reject_flow(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-REJ")
    dev = _token(client, "dev1")

    req_resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev),
    )
    request_id = req_resp.json()["request"]["id"]

    reject_resp = client.post(
        f"/api/key-requests/{request_id}/reject",
        json={"rejection_reason": "Budget exhausted"},
        headers=_auth(admin),
    )
    assert reject_resp.status_code == 200
    body = reject_resp.json()
    assert body["request"]["status"] == "rejected"
    assert body["request"]["rejection_reason"] == "Budget exhausted"
    assert body["key"] is None


# ---------------------------------------------------------------------------
# Scoping / visibility
# ---------------------------------------------------------------------------


def test_developer_sees_own_requests_only(
    client: TestClient, seeded: Session
) -> None:
    admin = _token(client, "admin")
    cc1 = _create_cc(client, admin, code="CC-SC1")
    cc2 = _create_cc(client, admin, code="CC-SC2")

    dev1 = _token(client, "dev1")
    dev2 = _token(client, "dev2")

    client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc1["id"]},
        headers=_auth(dev1),
    )
    client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc2["id"]},
        headers=_auth(dev2),
    )

    resp = client.get("/api/key-requests", headers=_auth(dev1))
    assert resp.status_code == 200
    ids = {r["developer_username"] for r in resp.json()}
    assert ids == {"dev1"}


def test_cco_sees_their_cc_requests(
    client: TestClient, seeded: Session
) -> None:
    admin = _token(client, "admin")
    cc1 = _create_cc(client, admin, code="CC-CCO1")
    cc2 = _create_cc(client, admin, code="CC-CCO2")
    _make_cco_of(seeded, "ccowner1", cc1["id"])
    seeded.commit()

    dev1 = _token(client, "dev1")
    dev2 = _token(client, "dev2")
    client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc1["id"]},
        headers=_auth(dev1),
    )
    client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc2["id"]},
        headers=_auth(dev2),
    )

    cco = _token(client, "ccowner1")
    resp = client.get("/api/key-requests", headers=_auth(cco))
    assert resp.status_code == 200
    cc_codes = {r["cost_centre_code"] for r in resp.json()}
    # Sees cc1 (owned), does NOT see cc2
    assert "CC-CCO1" in cc_codes
    assert "CC-CCO2" not in cc_codes


def test_admin_sees_all_requests(
    client: TestClient, seeded: Session
) -> None:
    admin = _token(client, "admin")
    cc1 = _create_cc(client, admin, code="CC-ADM1")
    cc2 = _create_cc(client, admin, code="CC-ADM2")
    dev1 = _token(client, "dev1")
    dev2 = _token(client, "dev2")

    client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc1["id"]},
        headers=_auth(dev1),
    )
    client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc2["id"]},
        headers=_auth(dev2),
    )

    resp = client.get("/api/key-requests", headers=_auth(admin))
    assert resp.status_code == 200
    codes = {r["cost_centre_code"] for r in resp.json()}
    assert {"CC-ADM1", "CC-ADM2"} <= codes


# ---------------------------------------------------------------------------
# 409 conflict guards
# ---------------------------------------------------------------------------


def test_one_active_key_409(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-DUP1")
    dev = _token(client, "dev1")

    # First request → pending
    r1 = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev),
    )
    assert r1.status_code == 201
    request_id = r1.json()["request"]["id"]

    # Approve to create a key
    client.post(
        f"/api/key-requests/{request_id}/approve",
        json={},
        headers=_auth(admin),
    )

    # Now try to create another request for the same CC
    r2 = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev),
    )
    assert r2.status_code == 409


def test_duplicate_pending_409(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-PND")
    dev = _token(client, "dev1")

    r1 = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev),
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev),
    )
    assert r2.status_code == 409


def test_archived_cc_request_404_for_dev(
    client: TestClient, seeded: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-ARC2")
    client.post(f"/api/cost-centres/{cc['id']}/archive", headers=_auth(admin))

    dev = _token(client, "dev1")
    resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev),
    )
    assert resp.status_code == 404


def test_non_pending_approve_409(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-NPN")
    dev = _token(client, "dev1")

    req_resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev),
    )
    request_id = req_resp.json()["request"]["id"]

    # Approve once
    client.post(
        f"/api/key-requests/{request_id}/approve",
        json={},
        headers=_auth(admin),
    )

    # Attempt to approve again → 409
    resp = client.post(
        f"/api/key-requests/{request_id}/approve",
        json={},
        headers=_auth(admin),
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_cco_of_different_cc_cannot_approve(
    client: TestClient, seeded: Session
) -> None:
    """A CCO who can't see the request (owns a different CC) gets 404, not 403,
    so the endpoint doesn't disclose the request's existence."""
    admin = _token(client, "admin")
    cc1 = _create_cc(client, admin, code="CC-RB1")
    cc2 = _create_cc(client, admin, code="CC-RB2")

    # ccowner1 owns cc2, NOT cc1
    _make_cco_of(seeded, "ccowner1", cc2["id"])
    seeded.commit()

    dev = _token(client, "dev1")
    req_resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc1["id"]},
        headers=_auth(dev),
    )
    request_id = req_resp.json()["request"]["id"]

    cco = _token(client, "ccowner1")
    resp = client.post(
        f"/api/key-requests/{request_id}/approve",
        json={},
        headers=_auth(cco),
    )
    assert resp.status_code == 404


def test_other_developer_cannot_see_or_approve(
    client: TestClient, seeded: Session
) -> None:
    """A different developer can't see another's request → 404 (existence hidden)."""
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-DA")
    dev1 = _token(client, "dev1")
    dev2 = _token(client, "dev2")

    req_resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev1),
    )
    request_id = req_resp.json()["request"]["id"]

    resp = client.post(
        f"/api/key-requests/{request_id}/approve",
        json={},
        headers=_auth(dev2),
    )
    assert resp.status_code == 404


def test_own_developer_cannot_approve_own_request(
    client: TestClient, seeded: Session
) -> None:
    """The requesting developer can SEE their request but isn't a reviewer → 403."""
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-OWN")
    dev = _token(client, "dev1")

    req_resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev),
    )
    request_id = req_resp.json()["request"]["id"]

    resp = client.post(
        f"/api/key-requests/{request_id}/approve",
        json={},
        headers=_auth(dev),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Bearer token visibility
# ---------------------------------------------------------------------------


def test_bearer_token_present_in_provisioning_response(
    client: TestClient, seeded: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-BT1")
    dev = _token(client, "dev1")

    req_resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev),
    )
    request_id = req_resp.json()["request"]["id"]

    approve_resp = client.post(
        f"/api/key-requests/{request_id}/approve",
        json={},
        headers=_auth(admin),
    )
    key = approve_resp.json()["key"]
    assert key["bearer_token"] is not None
    assert key["bearer_token"].startswith("br-")


def test_bearer_token_not_in_get_response(
    client: TestClient, seeded: Session
) -> None:
    """GET endpoints do not return bearer tokens (they only come from provisioning)."""
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-BT2")
    dev = _token(client, "dev1")

    req_resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev),
    )
    request_id = req_resp.json()["request"]["id"]

    # GET the request — no bearer_token in the response
    get_resp = client.get(f"/api/key-requests/{request_id}", headers=_auth(dev))
    assert get_resp.status_code == 200
    # KeyRequestOut has no bearer_token field — just verify
    assert "bearer_token" not in get_resp.json()


# ---------------------------------------------------------------------------
# Audit rows
# ---------------------------------------------------------------------------


def test_audit_rows_written(
    client: TestClient, seeded: Session, db_session: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-AUD2")
    dev = _token(client, "dev1")
    dev_id = _user_id(db_session, "dev1")

    req_resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev),
    )
    request_id = req_resp.json()["request"]["id"]

    # key.requested row
    requested_row = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "key.requested",
            AuditLog.entity_id == request_id,
        )
    )
    assert requested_row is not None

    # Approve → key.approved + key.provisioned
    client.post(
        f"/api/key-requests/{request_id}/approve",
        json={},
        headers=_auth(admin),
    )

    approved_row = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "key.approved",
            AuditLog.entity_id == request_id,
        )
    )
    assert approved_row is not None

    provisioned_rows = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "key.provisioned")
    ).all()
    assert len(provisioned_rows) >= 1


def test_audit_rows_for_reject(
    client: TestClient, seeded: Session, db_session: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-AUD3")
    dev = _token(client, "dev1")

    req_resp = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev),
    )
    request_id = req_resp.json()["request"]["id"]

    client.post(
        f"/api/key-requests/{request_id}/reject",
        json={"rejection_reason": "No budget"},
        headers=_auth(admin),
    )

    row = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "key.rejected",
            AuditLog.entity_id == request_id,
        )
    )
    assert row is not None


# ---------------------------------------------------------------------------
# Archive cascade
# ---------------------------------------------------------------------------


def test_archive_cascade_revokes_key_and_rejects_pending(
    client: TestClient, seeded: Session, db_session: Session
) -> None:
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="CC-ARC3")
    dev1 = _token(client, "dev1")
    dev2 = _token(client, "dev2")

    # dev1: create request, approve it → active key
    r1 = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev1),
    )
    r1_id = r1.json()["request"]["id"]
    client.post(
        f"/api/key-requests/{r1_id}/approve",
        json={},
        headers=_auth(admin),
    )

    # dev2: pending request (unapproved)
    r2 = client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc["id"]},
        headers=_auth(dev2),
    )
    r2_id = r2.json()["request"]["id"]

    # Archive the CC
    arc = client.post(
        f"/api/cost-centres/{cc['id']}/archive", headers=_auth(admin)
    )
    assert arc.status_code == 200

    # dev1's key should be revoked
    dev1_key = db_session.scalar(
        select(Key).where(
            Key.cost_centre_id == cc["id"],
        )
    )
    assert dev1_key is not None
    assert dev1_key.status == "revoked"
    assert dev1_key.revoked_at is not None

    # dev2's pending request should be rejected
    r2_row = db_session.get(KeyRequest, r2_id)
    assert r2_row.status == "rejected"
    assert r2_row.rejection_reason == "Cost centre archived"

    # Audit rows for key.revoked and key.rejected exist
    revoked_row = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "key.revoked",
            AuditLog.entity_id == dev1_key.id,
        )
    )
    assert revoked_row is not None

    rejected_row = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "key.rejected",
            AuditLog.entity_id == r2_id,
        )
    )
    assert rejected_row is not None


# ---------------------------------------------------------------------------
# GET list ordering
# ---------------------------------------------------------------------------


def test_list_ordered_by_created_at_desc(
    client: TestClient, seeded: Session
) -> None:
    admin = _token(client, "admin")
    cc1 = _create_cc(client, admin, code="CC-ORD1")
    cc2 = _create_cc(client, admin, code="CC-ORD2")
    dev = _token(client, "dev1")

    client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc1["id"]},
        headers=_auth(dev),
    )

    # Reject first so dev can make a second
    all_reqs = client.get("/api/key-requests", headers=_auth(admin)).json()
    first_id = all_reqs[0]["id"]
    client.post(
        f"/api/key-requests/{first_id}/reject",
        json={"rejection_reason": "test"},
        headers=_auth(admin),
    )

    client.post(
        "/api/key-requests",
        json={"cost_centre_id": cc2["id"]},
        headers=_auth(dev),
    )

    resp = client.get("/api/key-requests", headers=_auth(admin))
    items = resp.json()
    # Verify created_at descending
    created_ats = [i["created_at"] for i in items]
    assert created_ats == sorted(created_ats, reverse=True)


# ---------------------------------------------------------------------------
# status filter
# ---------------------------------------------------------------------------


def test_list_status_filter(client: TestClient, seeded: Session) -> None:
    admin = _token(client, "admin")
    cc1 = _create_cc(client, admin, code="CC-SF1")
    cc2 = _create_cc(client, admin, code="CC-SF2")
    dev1 = _token(client, "dev1")
    dev2 = _token(client, "dev2")

    # dev1 → pending on cc1; dev2 → rejected on cc2
    client.post(
        "/api/key-requests", json={"cost_centre_id": cc1["id"]}, headers=_auth(dev1)
    )
    r2 = client.post(
        "/api/key-requests", json={"cost_centre_id": cc2["id"]}, headers=_auth(dev2)
    )
    client.post(
        f"/api/key-requests/{r2.json()['request']['id']}/reject",
        json={"rejection_reason": "no"},
        headers=_auth(admin),
    )

    pending = client.get("/api/key-requests?status=pending", headers=_auth(admin))
    assert {r["status"] for r in pending.json()} == {"pending"}
    rejected = client.get("/api/key-requests?status=rejected", headers=_auth(admin))
    assert {r["status"] for r in rejected.json()} == {"rejected"}


# ---------------------------------------------------------------------------
# Provisioning failure → 502, rollback + AWS compensation
# ---------------------------------------------------------------------------


class _FailingAws(MockAwsService):
    """Mock that creates the inference profile(s) then fails at provision_key.

    Lets us assert the failure is mapped to 502, the request stays pending
    (DB rolled back), and the freshly-created profile is compensated away
    (so the AWS state does not drift from the DB and a retry would work).
    """

    def provision_key(self, **kwargs):  # type: ignore[override]
        raise AwsServiceError("simulated provisioning failure")


def test_provisioning_failure_returns_502_and_rolls_back(
    client: TestClient, seeded: Session, db_session: Session
) -> None:
    failing = _FailingAws()
    app.dependency_overrides[get_aws_service] = lambda: failing
    try:
        admin = _token(client, "admin")
        cc = _create_cc(client, admin, code="CC-FAIL")
        dev = _token(client, "dev1")

        req_resp = client.post(
            "/api/key-requests",
            json={"cost_centre_id": cc["id"]},
            headers=_auth(dev),
        )
        request_id = req_resp.json()["request"]["id"]

        resp = client.post(
            f"/api/key-requests/{request_id}/approve",
            json={},
            headers=_auth(admin),
        )
        assert resp.status_code == 502, resp.text

        # No key was ever created (provision_key failed before the Key row).
        assert (
            db_session.scalar(select(Key).where(Key.cost_centre_id == cc["id"]))
            is None
        )
        # AWS side-effect compensated: the profile created mid-provisioning was
        # deleted, so the mock's state did not drift from the (rolled-back) DB and
        # a retry with a healthy service could recreate it. (The DB rollback itself
        # is handled by get_db in production; the shared test session is reset at
        # teardown.)
        assert failing._profile_index == {}
    finally:
        app.dependency_overrides.pop(get_aws_service, None)
