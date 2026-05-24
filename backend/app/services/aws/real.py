"""Real AWS implementation stub (``AWS_MODE=real``) — deferred to Phase 11.

Every method raises ``NotImplementedError`` for now. In Phase 11 this class gains
the ``boto3`` calls behind the same :class:`AwsService` interface:

* IAM — ``CreateUser`` / ``PutUserPolicy`` / ``CreateServiceSpecificCredential`` /
  ``ResetServiceSpecificCredential`` / ``UpdateServiceSpecificCredential`` /
  ``DeleteServiceSpecificCredential`` / ``DeleteUser``.
* Bedrock — ``CreateInferenceProfile`` / ``DeleteInferenceProfile``.
* CloudWatch — ``GetMetricStatistics`` for per-profile token counts.
* Invocation-log parsing for per-key drill-down.

No ``boto3`` import here — it arrives with the implementation.
"""

from __future__ import annotations

from datetime import datetime

from app.services.aws.base import (
    AwsService,
    InferenceProfileRef,
    KeyUsage,
    ProvisionedKey,
    TokenUsage,
)

_DEFERRED = "Real AWS integration arrives in Phase 11 (AWS_MODE=real)"


class RealAwsService(AwsService):
    """Placeholder for the real ``boto3``-backed implementation (Phase 11)."""

    def provision_key(
        self,
        *,
        iam_username: str,
        cost_centre_code: str,
        allowed_models: list[str],
        expiry_days: int,
    ) -> ProvisionedKey:
        raise NotImplementedError(_DEFERRED)

    def revoke_key(self, *, iam_username: str, credential_id: str) -> None:
        raise NotImplementedError(_DEFERRED)

    def disable_key(self, *, credential_id: str) -> None:
        raise NotImplementedError(_DEFERRED)

    def enable_key(self, *, credential_id: str) -> None:
        raise NotImplementedError(_DEFERRED)

    def reset_key(self, *, credential_id: str) -> str:
        raise NotImplementedError(_DEFERRED)

    def update_model_policy(
        self, *, iam_username: str, allowed_models: list[str]
    ) -> None:
        raise NotImplementedError(_DEFERRED)

    def create_inference_profile(
        self, *, cost_centre_code: str, model_id: str
    ) -> InferenceProfileRef:
        raise NotImplementedError(_DEFERRED)

    def delete_inference_profile(self, *, profile_arn: str) -> None:
        raise NotImplementedError(_DEFERRED)

    def get_usage_metrics(
        self, *, profile_arn: str, start: datetime, end: datetime
    ) -> TokenUsage:
        raise NotImplementedError(_DEFERRED)

    def parse_invocation_logs(self, *, since: datetime) -> list[KeyUsage]:
        raise NotImplementedError(_DEFERRED)
