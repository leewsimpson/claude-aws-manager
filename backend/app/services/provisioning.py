"""Provisioning service: orchestrates inference-profile creation and key
provisioning for an approved key request.

The function ``provision_for_request`` is called by the router **after** the
key request has been set to ``approved`` but **before** the commit.  It does
not commit — the router owns the transaction.  It flushes when it needs a
generated id from the DB.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.models.inference_profile import InferenceProfile
from app.models.key import Key
from app.models.key_request import KeyRequest
from app.models.cost_centre import CostCentre
from app.models.user import User
from app.schemas.key_request import InferenceProfileRefOut
from app.services.aws.base import AwsService

if TYPE_CHECKING:
    pass


def provision_for_request(
    db: Session,
    aws: AwsService,
    *,
    key_request: KeyRequest,
    constraints: dict,
    actor: User,
    ip_address: str | None,
) -> tuple[Key, str, list[InferenceProfileRefOut]]:
    """Provision an inference profile (per model) and a key for an approved request.

    Steps (in order):
    1. For each allowed model, look up or create the InferenceProfile row.
    2. Build the IAM username.
    3. Call aws.provision_key.
    4. Persist a Key row.
    5. Write a key.provisioned audit entry.

    Returns (key_row, bearer_token, list_of_profile_refs).
    Does NOT commit — the caller does.
    May raise AwsServiceError subclasses; let them propagate.
    """
    cc = db.get(CostCentre, key_request.cost_centre_id)
    developer = db.get(User, key_request.developer_id)
    allowed_models: list[str] = constraints["allowed_models"]

    # --- step 1: ensure one active inference profile per model ---------------
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
        else:
            ref = aws.create_inference_profile(
                cost_centre_code=cc.code, model_id=model_id
            )
            profile_row = InferenceProfile(
                cost_centre_id=cc.id,
                model_id=model_id,
                profile_arn=ref.profile_arn,
                profile_name=ref.profile_name,
                status="active",
            )
            db.add(profile_row)
            db.flush()
            profile_refs.append(
                InferenceProfileRefOut(
                    model_id=model_id,
                    profile_arn=ref.profile_arn,
                    profile_name=ref.profile_name,
                )
            )

    # --- step 2: build IAM username ------------------------------------------
    iam_username = f"claude-{developer.username}-{cc.code}".lower()

    # --- step 3: provision the key via AWS -----------------------------------
    expiry_days: int = constraints["expiry_days"]
    provisioned = aws.provision_key(
        iam_username=iam_username,
        cost_centre_code=cc.code,
        allowed_models=allowed_models,
        expiry_days=expiry_days,
    )

    # --- step 4: persist Key row ---------------------------------------------
    now_utc = datetime.now(timezone.utc)
    key = Key(
        developer_id=developer.id,
        cost_centre_id=cc.id,
        key_request_id=key_request.id,
        iam_username=iam_username,
        credential_id=provisioned.credential_id,
        status="active",
        allowed_models=allowed_models,
        rolling_limit=constraints.get("rolling_limit"),
        rolling_period_days=constraints.get("rolling_period_days"),
        lifetime_budget=constraints.get("lifetime_budget"),
        lifetime_spend=0,
        expires_at=now_utc + timedelta(days=expiry_days) if expiry_days else None,
    )
    db.add(key)
    db.flush()

    # --- step 5: audit key.provisioned ---------------------------------------
    record_audit(
        db,
        actor_id=actor.id,
        action="key.provisioned",
        entity_type="key",
        entity_id=key.id,
        new_values={
            "iam_username": iam_username,
            "credential_id": provisioned.credential_id,
            "allowed_models": allowed_models,
            "cost_centre_id": cc.id,
        },
        ip_address=ip_address,
    )

    return key, provisioned.bearer_token, profile_refs
