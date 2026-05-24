"""Phase 7 tests: pricing, poll cycle, and usage endpoints.

Covers:
- compute_cost maths (explicit cases).
- run_poll_cycle with an injected MockAwsService: snapshots written, lifetime
  spend updated, rolling stop/restart, lifetime stop, CC-budget stop.
- Endpoint scoping: GET /keys/{id}/usage, GET /cost-centres/{id}/usage,
  GET /usage/summary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

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
from app.models.usage_snapshot import UsageSnapshot
from app.models.user import User
from app.services.aws import MockAwsService, get_aws_service
from app.services.pricing import PRICING, compute_cost, seed_pricing
from app.services.usage_poller import run_poll_cycle
from app.services.aws.base import TokenUsage
from app.main import app


# ---------------------------------------------------------------------------
# Clock helper
# ---------------------------------------------------------------------------


class Clock:
    """Mutable, callable tz-aware UTC clock for deterministic accrual."""

    def __init__(self, now: datetime | None = None) -> None:
        self.now = now or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, minutes: float = 0.0) -> None:
        self.now += timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_aws():
    """Replace the lru_cache singleton with a fresh MockAwsService per test."""
    clock = Clock()
    mock = MockAwsService(clock=clock, base_tokens_per_minute=800_000)
    app.dependency_overrides[get_aws_service] = lambda: mock
    yield mock, clock
    app.dependency_overrides.pop(get_aws_service, None)


# ---------------------------------------------------------------------------
# HTTP helpers (mirrors test_keys.py style)
# ---------------------------------------------------------------------------


def _token(client: TestClient, username: str) -> str:
    resp = client.post(
        "/api/auth/login", json={"username": username, "password": username}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_cc(client: TestClient, token: str, code: str = "CC-TEST", **kwargs) -> dict:
    body = {"code": code, "name": f"Test CC {code}"}
    body.update(kwargs)
    resp = client.post("/api/cost-centres", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _make_cco_of(db: Session, username: str, cc_id: str) -> None:
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
    return approve_resp.json()["key"]


# ---------------------------------------------------------------------------
# compute_cost tests
# ---------------------------------------------------------------------------


class TestComputeCost:
    def test_sonnet_input_only(self) -> None:
        usage = TokenUsage(input_tokens=1000, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0)
        prices = PRICING["anthropic.claude-sonnet-4-6"]
        cost = compute_cost(usage, prices)
        # 1000/1000 * 0.003 = 0.003
        assert cost == Decimal("0.003")

    def test_all_token_types(self) -> None:
        usage = TokenUsage(
            input_tokens=1000,
            output_tokens=1000,
            cache_read_tokens=1000,
            cache_write_tokens=1000,
        )
        prices = PRICING["anthropic.claude-haiku-4-5"]
        cost = compute_cost(usage, prices)
        # 0.001 + 0.005 + 0.0001 + 0.00125 = 0.00735
        assert cost == Decimal("0.00735")

    def test_none_prices_returns_zero(self) -> None:
        usage = TokenUsage(input_tokens=10000, output_tokens=5000)
        cost = compute_cost(usage, None)
        assert cost == Decimal("0")

    def test_zero_usage_returns_zero(self) -> None:
        usage = TokenUsage()
        cost = compute_cost(usage, PRICING["anthropic.claude-opus-4-1"])
        assert cost == Decimal("0")

    def test_large_token_counts(self) -> None:
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=500_000)
        prices = PRICING["anthropic.claude-sonnet-4-6"]
        cost = compute_cost(usage, prices)
        # 1000*0.003 + 500*0.015 = 3 + 7.5 = 10.5
        assert cost == Decimal("10.5")


# ---------------------------------------------------------------------------
# seed_pricing test
# ---------------------------------------------------------------------------


def test_seed_pricing_idempotent(seeded: Session) -> None:
    seed_pricing(seeded)
    seed_pricing(seeded)  # second call must not error
    from app.models.pricing_cache import PricingCache
    rows = seeded.scalars(select(PricingCache)).all()
    model_ids = {r.model_id for r in rows}
    assert "anthropic.claude-sonnet-4-6" in model_ids
    assert "anthropic.claude-haiku-4-5" in model_ids
    assert "anthropic.claude-opus-4-1" in model_ids


# ---------------------------------------------------------------------------
# run_poll_cycle tests
# ---------------------------------------------------------------------------


def _build_scenario(
    db: Session,
    aws: MockAwsService,
    clock: Clock,
    *,
    cc_code: str = "CC-POLL",
    developer_username: str = "dev1",
    rolling_limit: float | None = None,
    rolling_period_days: int | None = None,
    lifetime_budget: float | None = None,
    cc_budget_cap: float | None = None,
) -> tuple[CostCentre, Key, str]:
    """Build the full DB + AWS scenario for a poll cycle test.

    Returns (cc, key, credential_id).
    """
    # Seed pricing so load_pricing works
    seed_pricing(db)

    admin = db.scalar(select(User).where(User.username == "admin"))
    developer = db.scalar(select(User).where(User.username == developer_username))
    assert admin is not None and developer is not None

    # Cost centre
    cc = CostCentre(
        code=cc_code,
        name=f"Poll Test {cc_code}",
        status="active",
        budget_cap=cc_budget_cap,
        created_by=admin.id,
    )
    db.add(cc)
    db.flush()

    model_id = "anthropic.claude-sonnet-4-6"

    # Create inference profile in AWS mock
    ref = aws.create_inference_profile(cost_centre_code=cc_code, model_id=model_id)
    iam_username = f"claude-{developer_username}-{cc_code.lower()}"

    # Persist inference profile
    profile = InferenceProfile(
        cost_centre_id=cc.id,
        model_id=model_id,
        profile_arn=ref.profile_arn,
        profile_name=ref.profile_name,
        status="active",
    )
    db.add(profile)
    db.flush()

    # Provision key in AWS
    provisioned = aws.provision_key(
        iam_username=iam_username,
        cost_centre_code=cc_code,
        allowed_models=[model_id],
        expiry_days=90,
    )

    # Fake a KeyRequest row (required FK)
    kr = KeyRequest(
        developer_id=developer.id,
        cost_centre_id=cc.id,
        status="approved",
        reviewed_by=admin.id,
    )
    db.add(kr)
    db.flush()

    # Persist key
    key = Key(
        developer_id=developer.id,
        cost_centre_id=cc.id,
        key_request_id=kr.id,
        iam_username=iam_username,
        credential_id=provisioned.credential_id,
        status="active",
        allowed_models=[model_id],
        rolling_limit=rolling_limit,
        rolling_period_days=rolling_period_days,
        lifetime_budget=lifetime_budget,
        lifetime_spend=0,
    )
    db.add(key)
    db.flush()

    return cc, key, provisioned.credential_id


def test_poll_cycle_writes_snapshots(seeded: Session, _fresh_aws) -> None:
    """A poll cycle writes both cloudwatch and invocation_log rows."""
    aws, clock = _fresh_aws
    t0 = clock.now

    cc, key, cred_id = _build_scenario(seeded, aws, clock, cc_code="CC-SNAP")
    # Advance clock so tokens accrue
    clock.advance(minutes=10)
    t1 = clock.now

    summary = run_poll_cycle(seeded, aws, since=t0, now=t1)

    assert summary["cloudwatch_rows"] >= 1
    assert summary["invocation_rows"] >= 1

    # Snapshots are in DB
    cw_rows = seeded.scalars(
        select(UsageSnapshot).where(
            UsageSnapshot.key_id.is_(None),
            UsageSnapshot.source == "cloudwatch",
        )
    ).all()
    assert len(cw_rows) >= 1

    inv_rows = seeded.scalars(
        select(UsageSnapshot).where(
            UsageSnapshot.key_id == key.id,
            UsageSnapshot.source == "invocation_log",
        )
    ).all()
    assert len(inv_rows) >= 1

    # lifetime_spend updated
    seeded.refresh(key)
    assert key.lifetime_spend > 0


def test_poll_cycle_monotonic_snapshots(seeded: Session, _fresh_aws) -> None:
    """Two consecutive cycles each add rows; lifetime_spend is monotonic."""
    aws, clock = _fresh_aws
    t0 = clock.now

    cc, key, cred_id = _build_scenario(seeded, aws, clock, cc_code="CC-MONO")
    clock.advance(minutes=5)
    t1 = clock.now

    run_poll_cycle(seeded, aws, since=t0, now=t1)
    seeded.refresh(key)
    spend1 = key.lifetime_spend

    clock.advance(minutes=5)
    t2 = clock.now
    run_poll_cycle(seeded, aws, since=t1, now=t2)
    seeded.refresh(key)
    spend2 = key.lifetime_spend

    assert spend2 >= spend1


def test_rolling_limit_stops_and_restarts_key(seeded: Session, _fresh_aws) -> None:
    """Key with rolling_limit stops when rolling spend exceeds it, restarts when window expires."""
    aws, clock = _fresh_aws
    t0 = clock.now

    # Very small rolling limit to trigger stop quickly
    # With 800k tokens/min and Sonnet pricing 0.003/1k input + 0.015/1k output + cache,
    # 1 minute ≈ roughly 800k total tokens × ~0.003 avg = ~$2.4/min
    # Use rolling_limit=0.01 (1 cent) so it stops after < 1 min of real accrual
    cc, key, cred_id = _build_scenario(
        seeded, aws, clock,
        cc_code="CC-ROLL",
        rolling_limit=0.01,
        rolling_period_days=1,
    )

    clock.advance(minutes=1)
    t1 = clock.now
    summary = run_poll_cycle(seeded, aws, since=t0, now=t1)

    seeded.refresh(key)
    # Key should be stopped due to rolling limit
    assert key.status == "stopped", f"Expected stopped, got {key.status}"
    assert summary["stopped"] >= 1

    # Confirm audit row
    audit_row = seeded.scalar(
        select(AuditLog).where(
            AuditLog.action == "key.stopped",
            AuditLog.entity_id == key.id,
        )
    )
    assert audit_row is not None
    assert audit_row.new_values["reason"] == "rolling_limit_exceeded"

    # Advance the clock beyond the rolling window (1 day + 1 min)
    # so that all invocation_log snapshots fall outside the window
    clock.advance(minutes=24 * 60 + 1)
    t2 = clock.now
    # Run a cycle with no new accrual since the period is different
    # (use t1 → t2 as since/now so no new tokens accrue for this window from t1)
    summary2 = run_poll_cycle(seeded, aws, since=t1, now=t2)

    seeded.refresh(key)
    # Rolling window no longer contains the old snapshot → should restart
    assert key.status == "active", f"Expected active after restart, got {key.status}"
    assert summary2["restarted"] >= 1

    restart_row = seeded.scalar(
        select(AuditLog).where(
            AuditLog.action == "key.restarted",
            AuditLog.entity_id == key.id,
        )
    )
    assert restart_row is not None


def test_lifetime_budget_stops_key(seeded: Session, _fresh_aws) -> None:
    """Key with lifetime_budget stops when lifetime spend exceeds it."""
    aws, clock = _fresh_aws
    t0 = clock.now

    cc, key, cred_id = _build_scenario(
        seeded, aws, clock,
        cc_code="CC-LIFE",
        lifetime_budget=0.01,
    )

    clock.advance(minutes=1)
    t1 = clock.now
    summary = run_poll_cycle(seeded, aws, since=t0, now=t1)

    seeded.refresh(key)
    assert key.status == "stopped"
    assert summary["stopped"] >= 1
    audit_row = seeded.scalar(
        select(AuditLog).where(
            AuditLog.action == "key.stopped",
            AuditLog.entity_id == key.id,
        )
    )
    assert audit_row is not None
    assert audit_row.new_values["reason"] == "lifetime_budget_exceeded"


def test_cc_budget_cap_stops_key(seeded: Session, _fresh_aws) -> None:
    """Key stops when the cost centre's budget_cap is reached."""
    aws, clock = _fresh_aws
    t0 = clock.now

    cc, key, cred_id = _build_scenario(
        seeded, aws, clock,
        cc_code="CC-BUDG",
        cc_budget_cap=0.01,
    )

    clock.advance(minutes=1)
    t1 = clock.now
    summary = run_poll_cycle(seeded, aws, since=t0, now=t1)

    seeded.refresh(key)
    assert key.status == "stopped"
    assert summary["stopped"] >= 1
    audit_row = seeded.scalar(
        select(AuditLog).where(
            AuditLog.action == "key.stopped",
            AuditLog.entity_id == key.id,
        )
    )
    assert audit_row is not None
    assert audit_row.new_values["reason"] == "cc_budget_exceeded"


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


def test_get_key_usage_owner_200(client: TestClient, seeded: Session, _fresh_aws) -> None:
    """Key owner gets 200 from GET /keys/{id}/usage."""
    aws, clock = _fresh_aws
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KU-OWN1")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    dev1_token = _token(client, "dev1")
    resp = client.get(f"/api/keys/{key_data['id']}/usage", headers=_auth(dev1_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["key_id"] == key_data["id"]
    assert "rolling_spend" in body
    assert "lifetime_spend" in body
    assert "snapshots" in body


def test_get_key_usage_other_dev_404(client: TestClient, seeded: Session, _fresh_aws) -> None:
    """Another developer gets 404 from GET /keys/{id}/usage."""
    aws, clock = _fresh_aws
    admin = _token(client, "admin")
    cc = _create_cc(client, admin, code="KU-VIS1")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin)

    dev2_token = _token(client, "dev2")
    resp = client.get(f"/api/keys/{key_data['id']}/usage", headers=_auth(dev2_token))
    assert resp.status_code == 404


def test_get_key_usage_admin_200(client: TestClient, seeded: Session, _fresh_aws) -> None:
    """Admin gets 200 from GET /keys/{id}/usage."""
    aws, clock = _fresh_aws
    admin_token = _token(client, "admin")
    cc = _create_cc(client, admin_token, code="KU-ADM1")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin_token)

    resp = client.get(f"/api/keys/{key_data['id']}/usage", headers=_auth(admin_token))
    assert resp.status_code == 200


def test_get_cc_usage_cco_200(client: TestClient, seeded: Session, _fresh_aws) -> None:
    """CCO of a cost centre gets 200 from GET /cost-centres/{id}/usage."""
    aws, clock = _fresh_aws
    admin_token = _token(client, "admin")
    cc = _create_cc(client, admin_token, code="CCU-CCO1")
    _make_cco_of(seeded, "ccowner1", cc["id"])
    seeded.commit()

    cco_token = _token(client, "ccowner1")
    resp = client.get(f"/api/cost-centres/{cc['id']}/usage", headers=_auth(cco_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["cost_centre_id"] == cc["id"]
    assert "total_spend" in body
    assert "keys" in body
    assert "by_model" in body


def test_get_cc_usage_unrelated_dev_403(client: TestClient, seeded: Session, _fresh_aws) -> None:
    """Unrelated developer gets 403 from GET /cost-centres/{id}/usage."""
    aws, clock = _fresh_aws
    admin_token = _token(client, "admin")
    cc = _create_cc(client, admin_token, code="CCU-VIS1")

    dev1_token = _token(client, "dev1")
    resp = client.get(f"/api/cost-centres/{cc['id']}/usage", headers=_auth(dev1_token))
    assert resp.status_code == 403


def test_get_cc_usage_admin_200(client: TestClient, seeded: Session, _fresh_aws) -> None:
    """Admin gets 200 from GET /cost-centres/{id}/usage."""
    aws, clock = _fresh_aws
    admin_token = _token(client, "admin")
    cc = _create_cc(client, admin_token, code="CCU-ADM1")

    resp = client.get(f"/api/cost-centres/{cc['id']}/usage", headers=_auth(admin_token))
    assert resp.status_code == 200


def test_get_usage_summary_admin_200(client: TestClient, seeded: Session, _fresh_aws) -> None:
    """Admin gets 200 from GET /usage/summary."""
    admin_token = _token(client, "admin")
    resp = client.get("/api/usage/summary", headers=_auth(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert "total_spend" in body
    assert "active_keys" in body
    assert "stopped_keys" in body
    assert "cost_centres" in body
    assert "by_model" in body


def test_get_usage_summary_dev_403(client: TestClient, seeded: Session, _fresh_aws) -> None:
    """Developer gets 403 from GET /usage/summary."""
    dev_token = _token(client, "dev1")
    resp = client.get("/api/usage/summary", headers=_auth(dev_token))
    assert resp.status_code == 403


def test_key_out_has_rolling_spend_field(client: TestClient, seeded: Session, _fresh_aws) -> None:
    """GET /keys/{id} response now includes rolling_spend field."""
    aws, clock = _fresh_aws
    admin_token = _token(client, "admin")
    cc = _create_cc(client, admin_token, code="KO-RS1")
    key_data = _provision_key(client, seeded, developer_username="dev1", cc_id=cc["id"], admin_token=admin_token)

    dev1_token = _token(client, "dev1")
    resp = client.get(f"/api/keys/{key_data['id']}", headers=_auth(dev1_token))
    assert resp.status_code == 200
    assert "rolling_spend" in resp.json()
