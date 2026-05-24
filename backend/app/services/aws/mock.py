"""In-memory mock of the AWS service layer (``AWS_MODE=mock``).

Pure in-memory: no ``boto3``, no DB, no network. Holds key and inference-profile
state in dicts and drives a :class:`UsageSimulator` for synthetic CloudWatch /
invocation-log usage. Used for day-to-day dev, offline work and behavioural tests.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.services.aws.base import (
    DEFAULT_ACCOUNT_ID,
    DEFAULT_REGION,
    AwsService,
    DuplicateKeyError,
    DuplicateProfileError,
    InferenceProfileRef,
    KeyNotFoundError,
    KeyUsage,
    ProfileNotFoundError,
    ProvisionedKey,
    TokenUsage,
    build_model_policy,
)
from app.services.aws.usage import UsageSimulator

# Short names for the model ids we expect; anything else falls back to the last
# dotted segment with a trailing version stripped.
_MODEL_SHORT = {
    "anthropic.claude-sonnet-4-6": "sonnet",
    "anthropic.claude-haiku-4-5": "haiku",
    "anthropic.claude-opus-4-1": "opus",
}


def _model_short(model_id: str) -> str:
    """Map a model id to a short profile-name token (e.g. ``sonnet``)."""
    if model_id in _MODEL_SHORT:
        return _MODEL_SHORT[model_id]
    tail = model_id.rsplit(".", 1)[-1]
    # Strip a trailing ``-<digits>(-<digits>...)`` version suffix, leaving the family name.
    parts = tail.split("-")
    while len(parts) > 1 and parts[-1].isdigit():
        parts.pop()
    return "-".join(parts)


@dataclass
class _KeyState:
    """In-memory representation of a provisioned key."""

    credential_id: str
    iam_username: str
    cost_centre_code: str
    allowed_models: list[str]
    policy: dict
    expires_at: datetime
    model_profiles: dict[str, str]
    status: str = "active"  # 'active' | 'inactive'


@dataclass
class _ProfileState:
    """In-memory representation of an inference profile."""

    profile_arn: str
    profile_name: str
    cost_centre_code: str
    model_id: str
    status: str = "active"  # 'active' | 'deleted'


def _new_credential_id() -> str:
    # Illustrative only — NOT a real Bedrock/IAM credential id format.
    return "ACCA" + secrets.token_hex(8).upper()


def _new_bearer_token() -> str:
    # Illustrative only — NOT a real Bedrock bearer token format.
    return "br-" + secrets.token_urlsafe(32)


class MockAwsService(AwsService):
    """In-memory implementation of :class:`AwsService`."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        region: str = DEFAULT_REGION,
        account_id: str = DEFAULT_ACCOUNT_ID,
        base_tokens_per_minute: int = 8000,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._region = region
        self._account_id = account_id
        self._sim = UsageSimulator(
            clock=self._clock, base_tokens_per_minute=base_tokens_per_minute
        )
        self._keys: dict[str, _KeyState] = {}
        self._key_by_username: dict[str, str] = {}
        self._profiles: dict[str, _ProfileState] = {}
        # (cost_centre_code, model_id) -> ARN of the single active profile.
        self._profile_index: dict[tuple[str, str], str] = {}

    # -- keys -----------------------------------------------------------------

    def provision_key(
        self,
        *,
        iam_username: str,
        cost_centre_code: str,
        allowed_models: list[str],
        expiry_days: int,
    ) -> ProvisionedKey:
        if iam_username in self._key_by_username:
            raise DuplicateKeyError(
                f"IAM user {iam_username!r} already has a provisioned key"
            )
        now = self._clock()
        credential_id = _new_credential_id()
        bearer_token = _new_bearer_token()
        policy = build_model_policy(allowed_models, account_id=self._account_id)
        # Models without a profile for this CC are simply absent — realistic: no
        # CloudWatch attribution until a profile exists for that (CC, model).
        model_profiles = {
            model_id: self._profile_index[(cost_centre_code, model_id)]
            for model_id in allowed_models
            if (cost_centre_code, model_id) in self._profile_index
        }
        self._keys[credential_id] = _KeyState(
            credential_id=credential_id,
            iam_username=iam_username,
            cost_centre_code=cost_centre_code,
            allowed_models=list(allowed_models),
            policy=policy,
            expires_at=now + timedelta(days=expiry_days),
            model_profiles=model_profiles,
        )
        self._key_by_username[iam_username] = credential_id
        self._sim.register_key(
            credential_id=credential_id,
            iam_username=iam_username,
            cost_centre_code=cost_centre_code,
            model_profiles=model_profiles,
            provisioned_at=now,
        )
        return ProvisionedKey(credential_id=credential_id, bearer_token=bearer_token)

    def revoke_key(self, *, iam_username: str, credential_id: str) -> None:
        key = self._keys.get(credential_id)
        if key is None or key.iam_username != iam_username:
            raise KeyNotFoundError(
                f"No key {credential_id!r} for IAM user {iam_username!r}"
            )
        del self._keys[credential_id]
        self._key_by_username.pop(iam_username, None)
        self._sim.remove_key(credential_id=credential_id)

    def disable_key(self, *, credential_id: str) -> None:
        key = self._require_key(credential_id)
        key.status = "inactive"  # idempotent — already-inactive is a no-op
        self._sim.set_key_state(
            credential_id=credential_id, active=False, at=self._clock()
        )

    def enable_key(self, *, credential_id: str) -> None:
        key = self._require_key(credential_id)
        key.status = "active"  # idempotent — already-active is a no-op
        self._sim.set_key_state(
            credential_id=credential_id, active=True, at=self._clock()
        )

    def reset_key(self, *, credential_id: str) -> str:
        self._require_key(credential_id)
        # Old token is conceptually invalidated; the mock persists no token and
        # simply returns a fresh one.
        return _new_bearer_token()

    def update_model_policy(
        self, *, iam_username: str, allowed_models: list[str]
    ) -> None:
        credential_id = self._key_by_username.get(iam_username)
        if credential_id is None:
            raise KeyNotFoundError(f"No key for IAM user {iam_username!r}")
        key = self._keys[credential_id]
        key.allowed_models = list(allowed_models)
        key.policy = build_model_policy(allowed_models, account_id=self._account_id)
        # NOTE: the mock does not reroute sim profiles on a policy change — full
        # profile/model reroute is a Phase 11 concern.

    # -- inference profiles ---------------------------------------------------

    def create_inference_profile(
        self, *, cost_centre_code: str, model_id: str
    ) -> InferenceProfileRef:
        if (cost_centre_code, model_id) in self._profile_index:
            raise DuplicateProfileError(
                f"Active profile already exists for ({cost_centre_code}, {model_id})"
            )
        profile_name = (
            f"{cost_centre_code.lower().replace('-', '')}-{_model_short(model_id)}"
        )
        profile_arn = (
            f"arn:aws:bedrock:{self._region}:{self._account_id}"
            f":application-inference-profile/{profile_name}-{secrets.token_hex(4)}"
        )
        self._profiles[profile_arn] = _ProfileState(
            profile_arn=profile_arn,
            profile_name=profile_name,
            cost_centre_code=cost_centre_code,
            model_id=model_id,
        )
        self._profile_index[(cost_centre_code, model_id)] = profile_arn
        return InferenceProfileRef(profile_arn=profile_arn, profile_name=profile_name)

    def delete_inference_profile(self, *, profile_arn: str) -> None:
        profile = self._profiles.get(profile_arn)
        if profile is None:
            raise ProfileNotFoundError(f"Unknown profile ARN {profile_arn!r}")
        profile.status = "deleted"
        self._profile_index.pop((profile.cost_centre_code, profile.model_id), None)

    # -- usage ----------------------------------------------------------------

    def get_usage_metrics(
        self, *, profile_arn: str, start: datetime, end: datetime
    ) -> TokenUsage:
        # Unknown profile → simulator returns zero usage (no error).
        return self._sim.profile_usage(profile_arn=profile_arn, start=start, end=end)

    def parse_invocation_logs(self, *, since: datetime) -> list[KeyUsage]:
        return self._sim.key_usage_since(since=since)

    # -- internals ------------------------------------------------------------

    def _require_key(self, credential_id: str) -> _KeyState:
        key = self._keys.get(credential_id)
        if key is None:
            raise KeyNotFoundError(f"Unknown credential id {credential_id!r}")
        return key
