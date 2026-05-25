"""Provisioning service: orchestrates inference-profile creation and key
provisioning for an approved key request.

``provision_for_request`` is called by the router **after** the key request has
been set to ``approved`` but **before** the commit. It does not commit — the
router owns the transaction — and flushes when it needs a generated id.

**AWS/DB consistency:** the AWS layer is mutated (profiles, key) before the DB
commit, so its side-effects are *not* covered by the DB transaction. To keep the
two in sync, every AWS mutation this call makes is tracked; on **any** failure —
during provisioning *or* at the router's commit — :func:`compensate_aws` best-effort
undoes them (delete freshly-created profiles, revoke the freshly-provisioned key),
mirroring the DB rollback. Without this, a failed approval would leave orphaned
AWS state and could become un-retryable (e.g. ``DuplicateProfileError`` on retry).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.models.cost_centre import CostCentre
from app.models.inference_profile import InferenceProfile
from app.models.key import Key
from app.models.key_request import KeyRequest
from app.models.user import User
from app.schemas.key_request import InferenceProfileRefOut
from app.services.aws.base import AwsService, AwsServiceError


@dataclass
class ProvisionOutcome:
    """Result of a successful provisioning, plus handles for compensation."""

    key: Key
    profile_refs: list[InferenceProfileRefOut]
    # AWS side-effects this call created — used to compensate on a later commit failure.
    created_profile_arns: list[str] = field(default_factory=list)
    iam_username: str | None = None
    # True once the IAM identity was created (so compensation deletes it). The
    # credential is NOT issued here — the developer claims it on retrieval.
    identity_created: bool = False


def compensate_aws(
    aws: AwsService,
    *,
    created_profile_arns: list[str],
    iam_username: str | None = None,
    credential_id: str | None = None,
    identity_created: bool = False,
) -> None:
    """Best-effort undo of AWS side-effects when the DB transaction is rolled back.

    Swallows :class:`AwsServiceError` — compensation is opportunistic; the goal is
    to avoid orphaned AWS state, not to guarantee it (a residual orphan is far less
    harmful than a hard failure masking the original error).

    Tears down (in order): an issued credential (post-claim), an unclaimed identity
    (post-approval), then any freshly created inference profiles.
    """
    if credential_id is not None and iam_username is not None:
        try:
            aws.revoke_key(iam_username=iam_username, credential_id=credential_id)
        except AwsServiceError:
            pass
    elif identity_created and iam_username is not None:
        try:
            aws.delete_key_identity(iam_username=iam_username)
        except AwsServiceError:
            pass
    for arn in created_profile_arns:
        try:
            aws.delete_inference_profile(profile_arn=arn)
        except AwsServiceError:
            pass


def provision_for_request(
    db: Session,
    aws: AwsService,
    *,
    key_request: KeyRequest,
    constraints: dict,
    actor: User,
    ip_address: str | None,
) -> ProvisionOutcome:
    """Provision an inference profile (per model) and the IAM identity for an approved request.

    The bearer token is deliberately **not** minted here — the approver must never see
    it. The key lands in the ``ready`` state with ``credential_id = NULL``; the developer
    later issues the credential via ``POST /keys/{id}/retrieve``.

    Steps (in order):
    1. For each allowed model, look up or create the InferenceProfile row.
    2. Build the IAM username.
    3. Call aws.create_key_identity (IAM user + policy, no credential).
    4. Persist a 'ready' Key row (credential_id NULL).
    5. Write a key.provisioned audit entry.

    Returns a :class:`ProvisionOutcome`. Does NOT commit — the caller does.
    On any failure mid-provisioning, AWS side-effects are compensated before the
    exception propagates (the caller still maps it to an HTTP status).
    """
    cc = db.get(CostCentre, key_request.cost_centre_id)
    developer = db.get(User, key_request.developer_id)
    allowed_models: list[str] = constraints["allowed_models"]
    iam_username = f"claude-{developer.username}-{cc.code}".lower()

    created_profile_arns: list[str] = []
    identity_created = False

    try:
        # --- step 1: ensure one active inference profile per model ----------
        profile_refs: list[InferenceProfileRefOut] = []
        for model_id in allowed_models:
            existing = db.scalar(
                select(InferenceProfile).where(
                    InferenceProfile.cost_centre_id == cc.id,
                    InferenceProfile.model_id == model_id,
                    InferenceProfile.status == "active",
                )
            )
            if existing is not None:
                profile_refs.append(
                    InferenceProfileRefOut(
                        model_id=existing.model_id,
                        profile_arn=existing.profile_arn,
                        profile_name=existing.profile_name,
                    )
                )
                continue

            ref = aws.create_inference_profile(
                cost_centre_code=cc.code, model_id=model_id
            )
            created_profile_arns.append(ref.profile_arn)
            db.add(
                InferenceProfile(
                    cost_centre_id=cc.id,
                    model_id=model_id,
                    profile_arn=ref.profile_arn,
                    profile_name=ref.profile_name,
                    status="active",
                )
            )
            db.flush()
            profile_refs.append(
                InferenceProfileRefOut(
                    model_id=model_id,
                    profile_arn=ref.profile_arn,
                    profile_name=ref.profile_name,
                )
            )

        # --- step 2+3: provision the key via AWS ----------------------------
        expiry_days: int | None = constraints.get("expiry_days")
        expires_at_str: str | None = constraints.get("expires_at")

        # Determine the actual expiry_days for AWS and the final expires_at for the key
        if expires_at_str:
            from datetime import datetime as _dt
            expires_at_dt = _dt.fromisoformat(expires_at_str)
            # Calculate days from now for the AWS call
            now_utc = datetime.now(timezone.utc)
            delta = expires_at_dt - now_utc
            aws_expiry_days = max(int(delta.total_seconds() / 86400), 1)
        elif expiry_days:
            aws_expiry_days = expiry_days
            now_utc = datetime.now(timezone.utc)
            expires_at_dt = now_utc + timedelta(days=expiry_days)
        else:
            aws_expiry_days = 90  # fallback
            now_utc = datetime.now(timezone.utc)
            expires_at_dt = now_utc + timedelta(days=90)

        aws.create_key_identity(
            iam_username=iam_username,
            cost_centre_code=cc.code,
            allowed_models=allowed_models,
            expiry_days=aws_expiry_days,
        )
        identity_created = True

        # --- step 4: persist 'ready' Key row (no credential yet) ------------
        if not expires_at_str:
            now_utc = datetime.now(timezone.utc)
        key = Key(
            developer_id=developer.id,
            cost_centre_id=cc.id,
            key_request_id=key_request.id,
            iam_username=iam_username,
            credential_id=None,
            status="ready",
            allowed_models=allowed_models,
            rolling_limit=constraints.get("rolling_limit"),
            rolling_period_days=constraints.get("rolling_period_days"),
            lifetime_budget=constraints.get("lifetime_budget"),
            lifetime_spend=0,
            expires_at=expires_at_dt,
        )
        db.add(key)
        db.flush()

        # --- step 5: audit key.provisioned ----------------------------------
        record_audit(
            db,
            actor_id=actor.id,
            action="key.provisioned",
            entity_type="key",
            entity_id=key.id,
            new_values={
                "iam_username": iam_username,
                "allowed_models": allowed_models,
                "cost_centre_id": cc.id,
                "status": "ready",
            },
            ip_address=ip_address,
        )
    except Exception:
        # The DB transaction will be rolled back by the caller; undo AWS side-effects
        # so the mock/real AWS state does not drift from the DB.
        compensate_aws(
            aws,
            created_profile_arns=created_profile_arns,
            iam_username=iam_username,
            identity_created=identity_created,
        )
        raise

    return ProvisionOutcome(
        key=key,
        profile_refs=profile_refs,
        created_profile_arns=created_profile_arns,
        iam_username=iam_username,
        identity_created=identity_created,
    )
