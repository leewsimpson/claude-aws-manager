"""AWS service interface, value objects, exceptions and the IAM policy builder.

App code provisions and governs Bedrock API Keys exclusively through
:class:`AwsService`; it never touches ``boto3`` directly. Day-to-day dev runs the
in-memory mock (:class:`~app.services.aws.mock.MockAwsService`); real ``boto3``
calls land in Phase 11 behind this same interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

DEFAULT_REGION = "ap-southeast-2"
DEFAULT_ACCOUNT_ID = "123456789012"


@dataclass(frozen=True)
class ProvisionedKey:
    """A freshly provisioned key. The bearer token is shown once and never persisted by callers."""

    credential_id: str
    bearer_token: str


@dataclass(frozen=True)
class TokenUsage:
    """Token counts for a profile or key over a window."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Sum of the four token counts."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )


@dataclass(frozen=True)
class KeyUsage:
    """Per-key usage drilled from invocation logs (one IAM user = one key)."""

    credential_id: str
    iam_username: str
    model_id: str
    usage: TokenUsage


@dataclass(frozen=True)
class InferenceProfileRef:
    """A reference to a provisioned application inference profile."""

    profile_arn: str
    profile_name: str


class AwsServiceError(Exception):
    """Base class for AWS service-layer errors."""


class KeyNotFoundError(AwsServiceError):
    """Raised when a key (by credential id or IAM username) is not found."""


class ProfileNotFoundError(AwsServiceError):
    """Raised when an inference profile ARN is not found."""


class DuplicateProfileError(AwsServiceError):
    """Raised when an active profile already exists for a (cost centre, model) pair."""


class DuplicateKeyError(AwsServiceError):
    """Raised when the IAM username already has a provisioned key."""


@runtime_checkable
class UsageSimulatorProtocol(Protocol):
    """Shape of the usage simulator the mock drives (implemented in ``usage.py``)."""

    def register_key(
        self,
        *,
        credential_id: str,
        iam_username: str,
        cost_centre_code: str,
        model_profiles: dict[str, str],
        provisioned_at: datetime,
    ) -> None: ...

    def set_key_state(
        self, *, credential_id: str, active: bool, at: datetime
    ) -> None: ...

    def remove_key(self, *, credential_id: str) -> None: ...

    def profile_usage(
        self, *, profile_arn: str, start: datetime, end: datetime
    ) -> TokenUsage: ...

    def key_usage_since(self, *, since: datetime) -> list[KeyUsage]: ...


def build_model_policy(
    allowed_models: list[str], *, region: str = "*", account_id: str = "*"
) -> dict:
    """Build the inline IAM policy scoping ``bedrock:InvokeModel`` to exact model ARNs.

    Enforces Decision #3 + #13: no wildcards on the model id. Mirrors the policy in
    ``docs/design-decisions.md`` §3 — three statements:

    * ``AllowModelInvocation`` — ``InvokeModel`` + ``InvokeModelWithResponseStream`` on
      ``foundation-model/<each allowed model>`` plus ``application-inference-profile/*``.
    * ``AllowInferenceProfileResolution`` — ``GetInferenceProfile``/``ListInferenceProfiles``
      on ``inference-profile/*`` + ``application-inference-profile/*``.
    * ``AllowBearerTokenUsage`` — ``bedrock:CallWithBearerToken`` on ``*``.

    Foundation-model ARNs are region- and account-agnostic
    (``arn:aws:bedrock:*::foundation-model/<model_id>``); the ``region``/``account_id``
    args scope only the inference-profile resources.
    """
    foundation_arns = [
        f"arn:aws:bedrock:*::foundation-model/{model_id}"
        for model_id in allowed_models
    ]
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowModelInvocation",
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                "Resource": [
                    *foundation_arns,
                    f"arn:aws:bedrock:{region}:{account_id}:application-inference-profile/*",
                ],
            },
            {
                "Sid": "AllowInferenceProfileResolution",
                "Effect": "Allow",
                "Action": [
                    "bedrock:GetInferenceProfile",
                    "bedrock:ListInferenceProfiles",
                ],
                "Resource": [
                    f"arn:aws:bedrock:{region}:{account_id}:inference-profile/*",
                    f"arn:aws:bedrock:{region}:{account_id}:application-inference-profile/*",
                ],
            },
            {
                "Sid": "AllowBearerTokenUsage",
                "Effect": "Allow",
                "Action": "bedrock:CallWithBearerToken",
                "Resource": "*",
            },
        ],
    }


class AwsService(ABC):
    """Interface for provisioning and governing Bedrock API Keys."""

    # -- rehydration (concrete no-ops so RealAwsService inherits them) --------

    def rehydrate_profile(
        self,
        *,
        cost_centre_code: str,
        model_id: str,
        profile_arn: str,
        profile_name: str,
    ) -> None:
        """Re-populate in-memory profile state from the DB on startup. No-op by default."""

    def rehydrate_key(
        self,
        *,
        credential_id: str,
        iam_username: str,
        cost_centre_code: str,
        allowed_models: list[str],
        model_profiles: dict[str, str],
        provisioned_at: datetime,
        active: bool,
    ) -> None:
        """Re-populate in-memory key state from the DB on startup. No-op by default."""

    # -- abstract interface ---------------------------------------------------

    @abstractmethod
    def provision_key(
        self,
        *,
        iam_username: str,
        cost_centre_code: str,
        allowed_models: list[str],
        expiry_days: int,
    ) -> ProvisionedKey:
        """Create a key (backing IAM user + scoped policy) and return its bearer token."""

    @abstractmethod
    def revoke_key(self, *, iam_username: str, credential_id: str) -> None:
        """Delete the key and its backing IAM user."""

    @abstractmethod
    def disable_key(self, *, credential_id: str) -> None:
        """Set the key inactive (hard stop). Idempotent."""

    @abstractmethod
    def enable_key(self, *, credential_id: str) -> None:
        """Set the key active. Idempotent."""

    @abstractmethod
    def reset_key(self, *, credential_id: str) -> str:
        """Regenerate the bearer token (invalidating the old) and return the new one."""

    @abstractmethod
    def update_model_policy(
        self, *, iam_username: str, allowed_models: list[str]
    ) -> None:
        """Rebuild the inline IAM policy for the user from a new allowed-models list."""

    @abstractmethod
    def create_inference_profile(
        self, *, cost_centre_code: str, model_id: str
    ) -> InferenceProfileRef:
        """Create an application inference profile for a (cost centre, model) pair."""

    @abstractmethod
    def delete_inference_profile(self, *, profile_arn: str) -> None:
        """Delete an application inference profile by ARN."""

    @abstractmethod
    def get_usage_metrics(
        self, *, profile_arn: str, start: datetime, end: datetime
    ) -> TokenUsage:
        """Return CloudWatch token counts for a profile over a window."""

    @abstractmethod
    def parse_invocation_logs(self, *, since: datetime) -> list[KeyUsage]:
        """Return per-key usage drilled from invocation logs since a point in time."""
