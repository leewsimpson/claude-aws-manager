"""L2 unit suite for the AWS mock layer (Phase 4, Stream B).

Pure/offline: no DB, no HTTP, no conftest fixtures. Drives a controllable
clock through :class:`MockAwsService` to exercise lifecycle, IAM policy
shape, inference profiles, usage accrual (incl. pause/resume + windowing),
and AWS_MODE factory routing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services.aws import _build, get_aws_service
from app.services.aws.base import (
    AwsServiceError,
    DuplicateKeyError,
    DuplicateProfileError,
    KeyNotFoundError,
    ProfileNotFoundError,
    TokenUsage,
)
from app.services.aws.mock import MockAwsService, build_model_policy
from app.services.aws.real import RealAwsService

SONNET = "anthropic.claude-sonnet-4-6"
HAIKU = "anthropic.claude-haiku-4-5"
CC = "CC-1234"


class Clock:
    """Mutable, callable tz-aware UTC clock for deterministic accrual."""

    def __init__(self, now: datetime | None = None) -> None:
        self.now = now or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, minutes: float = 0.0) -> None:
        self.now += timedelta(minutes=minutes)

    def __iadd__(self, delta: timedelta) -> "Clock":
        self.now += delta
        return self


def _svc(clock: Clock | None = None) -> MockAwsService:
    return MockAwsService(clock=clock or Clock())


# --------------------------------------------------------------------------
# Lifecycle / state machine
# --------------------------------------------------------------------------


class TestLifecycle:
    def test_provision_returns_credential_and_token(self) -> None:
        svc = _svc()
        prov = svc.provision_key(
            iam_username="claude-dev1-cc1234",
            cost_centre_code=CC,
            allowed_models=[SONNET],
            expiry_days=90,
        )
        assert prov.credential_id
        assert prov.bearer_token

    def test_distinct_users_get_distinct_credentials_and_tokens(self) -> None:
        svc = _svc()
        a = svc.provision_key(
            iam_username="claude-dev1-cc1234",
            cost_centre_code=CC,
            allowed_models=[SONNET],
            expiry_days=90,
        )
        b = svc.provision_key(
            iam_username="claude-dev2-cc1234",
            cost_centre_code=CC,
            allowed_models=[SONNET],
            expiry_days=90,
        )
        assert a.credential_id != b.credential_id
        assert a.bearer_token != b.bearer_token

    def test_duplicate_iam_username_raises(self) -> None:
        svc = _svc()
        svc.provision_key(
            iam_username="claude-dev1-cc1234",
            cost_centre_code=CC,
            allowed_models=[SONNET],
            expiry_days=90,
        )
        with pytest.raises(DuplicateKeyError):
            svc.provision_key(
                iam_username="claude-dev1-cc1234",
                cost_centre_code=CC,
                allowed_models=[SONNET],
                expiry_days=90,
            )

    def test_reset_key_returns_new_token(self) -> None:
        svc = _svc()
        prov = svc.provision_key(
            iam_username="claude-dev1-cc1234",
            cost_centre_code=CC,
            allowed_models=[SONNET],
            expiry_days=90,
        )
        new_token = svc.reset_key(credential_id=prov.credential_id)
        assert new_token
        assert new_token != prov.bearer_token

    def test_reset_unknown_raises(self) -> None:
        svc = _svc()
        with pytest.raises(KeyNotFoundError):
            svc.reset_key(credential_id="does-not-exist")

    def test_disable_enable_no_error(self) -> None:
        svc = _svc()
        prov = svc.provision_key(
            iam_username="claude-dev1-cc1234",
            cost_centre_code=CC,
            allowed_models=[SONNET],
            expiry_days=90,
        )
        svc.disable_key(credential_id=prov.credential_id)
        svc.enable_key(credential_id=prov.credential_id)

    def test_disable_idempotent(self) -> None:
        svc = _svc()
        prov = svc.provision_key(
            iam_username="claude-dev1-cc1234",
            cost_centre_code=CC,
            allowed_models=[SONNET],
            expiry_days=90,
        )
        svc.disable_key(credential_id=prov.credential_id)
        # second disable must not raise
        svc.disable_key(credential_id=prov.credential_id)

    def test_disable_unknown_raises(self) -> None:
        svc = _svc()
        with pytest.raises(KeyNotFoundError):
            svc.disable_key(credential_id="nope")

    def test_revoke_removes_key(self) -> None:
        svc = _svc()
        prov = svc.provision_key(
            iam_username="claude-dev1-cc1234",
            cost_centre_code=CC,
            allowed_models=[SONNET],
            expiry_days=90,
        )
        svc.revoke_key(
            iam_username="claude-dev1-cc1234", credential_id=prov.credential_id
        )
        with pytest.raises(KeyNotFoundError):
            svc.disable_key(credential_id=prov.credential_id)
        with pytest.raises(KeyNotFoundError):
            svc.reset_key(credential_id=prov.credential_id)

    def test_revoke_mismatched_username_raises(self) -> None:
        svc = _svc()
        prov = svc.provision_key(
            iam_username="claude-dev1-cc1234",
            cost_centre_code=CC,
            allowed_models=[SONNET],
            expiry_days=90,
        )
        with pytest.raises(KeyNotFoundError):
            svc.revoke_key(
                iam_username="claude-wrong-cc1234",
                credential_id=prov.credential_id,
            )

    def test_revoke_unknown_raises(self) -> None:
        svc = _svc()
        with pytest.raises(KeyNotFoundError):
            svc.revoke_key(iam_username="claude-x-cc1234", credential_id="nope")


# --------------------------------------------------------------------------
# IAM policy — exact ARNs (Decision #3/#13)
# --------------------------------------------------------------------------


class TestModelPolicy:
    def test_exact_model_arn_no_wildcard(self) -> None:
        policy = build_model_policy([SONNET])
        blob = json.dumps(policy)
        exact = f"arn:aws:bedrock:*::foundation-model/{SONNET}"
        assert exact in blob
        # no wildcard on the model name
        assert "claude-sonnet-*" not in blob
        assert f"foundation-model/{SONNET}" in blob

    def test_includes_required_actions_and_profile_resource(self) -> None:
        policy = build_model_policy([SONNET])
        blob = json.dumps(policy)
        assert "bedrock:InvokeModel" in blob
        assert "bedrock:CallWithBearerToken" in blob
        assert "application-inference-profile/*" in blob

    def test_structural_actions_present(self) -> None:
        policy = build_model_policy([SONNET, HAIKU])
        actions: set[str] = set()
        resources: set[str] = set()
        for stmt in policy["Statement"]:
            acts = stmt["Action"]
            actions.update([acts] if isinstance(acts, str) else acts)
            res = stmt["Resource"]
            resources.update([res] if isinstance(res, str) else res)
        assert "bedrock:InvokeModel" in actions
        assert "bedrock:CallWithBearerToken" in actions
        assert f"arn:aws:bedrock:*::foundation-model/{SONNET}" in resources
        assert f"arn:aws:bedrock:*::foundation-model/{HAIKU}" in resources


# --------------------------------------------------------------------------
# Inference profiles
# --------------------------------------------------------------------------


class TestInferenceProfiles:
    def test_create_returns_arn_and_name(self) -> None:
        svc = _svc()
        ref = svc.create_inference_profile(cost_centre_code=CC, model_id=SONNET)
        assert "application-inference-profile/" in ref.profile_arn
        assert "sonnet" in ref.profile_name.lower()

    def test_duplicate_active_pair_raises(self) -> None:
        svc = _svc()
        svc.create_inference_profile(cost_centre_code=CC, model_id=SONNET)
        with pytest.raises(DuplicateProfileError):
            svc.create_inference_profile(cost_centre_code=CC, model_id=SONNET)

    def test_recreate_after_delete(self) -> None:
        svc = _svc()
        ref = svc.create_inference_profile(cost_centre_code=CC, model_id=SONNET)
        svc.delete_inference_profile(profile_arn=ref.profile_arn)
        # same (cc, model) can be created again
        ref2 = svc.create_inference_profile(cost_centre_code=CC, model_id=SONNET)
        assert "application-inference-profile/" in ref2.profile_arn

    def test_delete_unknown_raises(self) -> None:
        svc = _svc()
        with pytest.raises(ProfileNotFoundError):
            svc.delete_inference_profile(
                profile_arn="arn:aws:bedrock:ap-southeast-2:123456789012:"
                "application-inference-profile/ghost"
            )


# --------------------------------------------------------------------------
# Usage accrual
# --------------------------------------------------------------------------


def _provision_with_profile(
    svc: MockAwsService,
    *,
    iam_username: str,
    model_id: str = SONNET,
    cost_centre_code: str = CC,
) -> tuple[str, str]:
    """Create a profile for (cc, model) and provision a key; return (cred, arn)."""
    ref = svc.create_inference_profile(
        cost_centre_code=cost_centre_code, model_id=model_id
    )
    prov = svc.provision_key(
        iam_username=iam_username,
        cost_centre_code=cost_centre_code,
        allowed_models=[model_id],
        expiry_days=90,
    )
    return prov.credential_id, ref.profile_arn


class TestUsageAccrual:
    def test_zero_at_start_then_grows(self) -> None:
        clock = Clock()
        svc = _svc(clock)
        t0 = clock.now
        _, arn = _provision_with_profile(svc, iam_username="claude-dev1-cc1234")

        zero = svc.get_usage_metrics(profile_arn=arn, start=t0, end=clock.now)
        assert zero.total_tokens == 0

        clock.advance(minutes=60)
        first = svc.get_usage_metrics(profile_arn=arn, start=t0, end=clock.now)
        assert first.total_tokens > 0
        # four categories present
        assert first.input_tokens > 0
        assert first.output_tokens > 0
        assert first.cache_read_tokens > 0
        assert first.cache_write_tokens > 0
        # cache-read heavy ratio: input < cache_read
        assert first.input_tokens < first.cache_read_tokens
        # order of magnitude ~ base*factor*60 (factor in [0.5,1.5])
        assert 0.5 * 8000 * 60 <= first.total_tokens <= 1.5 * 8000 * 60 * 1.01

        clock.advance(minutes=60)
        second = svc.get_usage_metrics(profile_arn=arn, start=t0, end=clock.now)
        assert second.total_tokens > first.total_tokens

    def test_unknown_profile_is_zero(self) -> None:
        clock = Clock()
        svc = _svc(clock)
        _provision_with_profile(svc, iam_username="claude-dev1-cc1234")
        clock.advance(minutes=60)
        usage = svc.get_usage_metrics(
            profile_arn="arn:aws:bedrock:ap-southeast-2:123456789012:"
            "application-inference-profile/ghost",
            start=clock.now - timedelta(minutes=60),
            end=clock.now,
        )
        assert usage.total_tokens == 0

    def test_pause_on_disable_does_not_accrue(self) -> None:
        """A disabled key stops accruing; the gap contributes nothing.

        Run a paused key (active 30m, idle 30m, active 30m → 60 active min) and
        an always-active reference key over the same 90-min span. Each key has
        its own deterministic rate, so we normalise by a clean 10-min active
        window per key, then compare active-minutes implied by the full span.
        """
        clock = Clock()
        svc = _svc(clock)
        t0 = clock.now
        cred_paused, arn_paused = _provision_with_profile(
            svc, iam_username="claude-paused-cc1234", cost_centre_code="CC-PAUSE"
        )
        _, arn_active = _provision_with_profile(
            svc, iam_username="claude-active-cc1234", cost_centre_code="CC-ACT"
        )

        # Per-key rate yardstick: first 10 minutes, both active.
        clock.advance(minutes=10)
        t_ref = clock.now
        paused_rate = (
            svc.get_usage_metrics(profile_arn=arn_paused, start=t0, end=t_ref)
            .total_tokens
            / 10.0
        )
        active_rate = (
            svc.get_usage_metrics(profile_arn=arn_active, start=t0, end=t_ref)
            .total_tokens
            / 10.0
        )

        clock.advance(minutes=20)  # 30 active min elapsed for both
        svc.disable_key(credential_id=cred_paused)
        clock.advance(minutes=30)  # paused idle; active accrues
        svc.enable_key(credential_id=cred_paused)
        clock.advance(minutes=30)  # both accrue

        paused = svc.get_usage_metrics(profile_arn=arn_paused, start=t0, end=clock.now)
        active = svc.get_usage_metrics(profile_arn=arn_active, start=t0, end=clock.now)
        assert paused.total_tokens > 0
        assert active.total_tokens > 0

        # Implied active-minutes from each key's own rate.
        paused_minutes = paused.total_tokens / paused_rate
        active_minutes = active.total_tokens / active_rate
        # Paused key saw ~60 active min; active reference saw ~90. Allow rounding slack.
        assert paused_minutes == pytest.approx(60, abs=1)
        assert active_minutes == pytest.approx(90, abs=1)
        # The 30 disabled minutes materially reduced accrual.
        assert paused_minutes < active_minutes * 0.8

    def test_windows_are_additive_and_monotonic(self) -> None:
        clock = Clock()
        svc = _svc(clock)
        t0 = clock.now
        _, arn = _provision_with_profile(svc, iam_username="claude-dev1-cc1234")

        clock.advance(minutes=40)
        t1 = clock.now
        clock.advance(minutes=40)
        t2 = clock.now

        w1 = svc.get_usage_metrics(profile_arn=arn, start=t0, end=t1)
        w2 = svc.get_usage_metrics(profile_arn=arn, start=t1, end=t2)
        whole = svc.get_usage_metrics(profile_arn=arn, start=t0, end=t2)

        assert w1.total_tokens > 0
        assert w2.total_tokens > 0
        # additive within rounding tolerance (floor rounding across 4 categories)
        assert abs((w1.total_tokens + w2.total_tokens) - whole.total_tokens) <= 8

    def test_invocation_logs_per_key(self) -> None:
        clock = Clock()
        svc = _svc(clock)
        t0 = clock.now
        cred, _ = _provision_with_profile(svc, iam_username="claude-dev1-cc1234")
        clock.advance(minutes=60)

        logs = svc.parse_invocation_logs(since=t0)
        assert len(logs) == 1
        ku = logs[0]
        assert ku.credential_id == cred
        assert ku.iam_username == "claude-dev1-cc1234"
        assert ku.model_id == SONNET
        assert ku.usage.total_tokens > 0

    def test_no_profile_for_model_yields_no_usage(self) -> None:
        clock = Clock()
        svc = _svc(clock)
        t0 = clock.now
        # provision WITHOUT creating a profile for the model
        svc.provision_key(
            iam_username="claude-orphan-cc1234",
            cost_centre_code="CC-ORPHAN",
            allowed_models=[SONNET],
            expiry_days=90,
        )
        clock.advance(minutes=60)
        logs = svc.parse_invocation_logs(since=t0)
        assert logs == []

    def test_multi_model_key_splits_burn_no_double_count(self) -> None:
        """A 2-model key's per-model logs sum to its single window burn, and each
        profile sees only the key's per-model share (no double-counting)."""
        clock = Clock()
        svc = _svc(clock)
        t0 = clock.now
        ref_sonnet = svc.create_inference_profile(cost_centre_code=CC, model_id=SONNET)
        ref_haiku = svc.create_inference_profile(cost_centre_code=CC, model_id=HAIKU)
        cred = svc.provision_key(
            iam_username="claude-dev1-cc1234",
            cost_centre_code=CC,
            allowed_models=[SONNET, HAIKU],
            expiry_days=90,
        ).credential_id
        clock.advance(minutes=60)

        logs = svc.parse_invocation_logs(since=t0)
        assert {ku.model_id for ku in logs} == {SONNET, HAIKU}
        assert all(ku.credential_id == cred for ku in logs)
        per_key_total = sum(ku.usage.total_tokens for ku in logs)

        sonnet = svc.get_usage_metrics(
            profile_arn=ref_sonnet.profile_arn, start=t0, end=clock.now
        )
        haiku = svc.get_usage_metrics(
            profile_arn=ref_haiku.profile_arn, start=t0, end=clock.now
        )
        # each profile gets ~half; the two halves ≈ the per-key total (floor slack)
        assert sonnet.total_tokens > 0 and haiku.total_tokens > 0
        assert abs((sonnet.total_tokens + haiku.total_tokens) - per_key_total) <= 16

    def test_two_keys_same_profile_sum(self) -> None:
        clock = Clock()
        svc = _svc(clock)
        t0 = clock.now
        ref = svc.create_inference_profile(cost_centre_code=CC, model_id=SONNET)
        svc.provision_key(
            iam_username="claude-dev1-cc1234",
            cost_centre_code=CC,
            allowed_models=[SONNET],
            expiry_days=90,
        )
        svc.provision_key(
            iam_username="claude-dev2-cc1234",
            cost_centre_code=CC,
            allowed_models=[SONNET],
            expiry_days=90,
        )
        clock.advance(minutes=60)

        metrics = svc.get_usage_metrics(
            profile_arn=ref.profile_arn, start=t0, end=clock.now
        )
        logs = svc.parse_invocation_logs(since=t0)
        assert len(logs) == 2
        log_sum = sum(ku.usage.total_tokens for ku in logs)
        # both keys feed the one profile; metric ≈ sum of per-key logs
        assert abs(metrics.total_tokens - log_sum) <= 8


# --------------------------------------------------------------------------
# Factory / AWS_MODE routing
# --------------------------------------------------------------------------


class TestFactory:
    def test_real_methods_raise_not_implemented(self) -> None:
        real = RealAwsService()
        with pytest.raises(NotImplementedError):
            real.provision_key(
                iam_username="x",
                cost_centre_code=CC,
                allowed_models=[SONNET],
                expiry_days=90,
            )

    def test_get_aws_service_returns_singleton(self) -> None:
        a = get_aws_service()
        b = get_aws_service()
        assert a is b

    def test_default_mode_is_mock(self) -> None:
        # default settings.aws_mode == "mock"
        svc = get_aws_service()
        assert isinstance(svc, MockAwsService)

    def test_build_routes_on_mode(self) -> None:
        assert isinstance(_build("mock"), MockAwsService)
        assert isinstance(_build("real"), RealAwsService)
        with pytest.raises(ValueError):
            _build("bogus")


def test_token_usage_total() -> None:
    """Sanity check on the frozen TokenUsage contract used throughout."""
    u = TokenUsage(
        input_tokens=1,
        output_tokens=2,
        cache_read_tokens=3,
        cache_write_tokens=4,
    )
    assert u.total_tokens == 10


def test_aws_service_error_base() -> None:
    """All mock exceptions derive from AwsServiceError."""
    for exc in (
        DuplicateKeyError,
        KeyNotFoundError,
        DuplicateProfileError,
        ProfileNotFoundError,
    ):
        assert issubclass(exc, AwsServiceError)
