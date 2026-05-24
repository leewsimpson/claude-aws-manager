"""Key management endpoints (Phase 6).

Mounted under ``/api`` → ``/api/keys``.

Roles:
- Developer: sees and revokes own keys; regenerates own keys.
- CCO: sees keys for their cost centres; revokes keys in their CCs;
  patches constraints on keys in their CCs.
- Admin: sees all keys; revokes, regenerates, and patches any key.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.deps import get_current_user
from app.core.request import client_ip as _client_ip
from app.db.session import get_db
from app.models.cost_centre import CostCentre
from app.models.cost_centre_owner import CostCentreOwner
from app.models.global_setting import GlobalSetting
from app.models.inference_profile import InferenceProfile
from app.models.key import Key
from app.models.usage_snapshot import UsageSnapshot
from app.models.user import User
from app.schemas.key import KeyConstraintsUpdate, KeyOut
from app.schemas.key_request import InferenceProfileRefOut, ProvisionedKeyOut
from app.schemas.usage import KeyUsageOut, UsageSnapshotOut
from app.services.aws import AwsService, AwsServiceError, KeyNotFoundError, get_aws_service
from app.services.provisioning import compensate_aws

router = APIRouter(prefix="/keys", tags=["keys"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_cco_of(db: Session, user_id: uuid.UUID, cc_id: uuid.UUID) -> bool:
    """Return True if user_id owns cc_id in cost_centre_owners."""
    row = db.scalar(
        select(CostCentreOwner).where(
            CostCentreOwner.user_id == user_id,
            CostCentreOwner.cost_centre_id == cc_id,
        )
    )
    return row is not None


def _owned_cc_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Return the set of cost-centre IDs this user owns as a CCO."""
    rows = db.scalars(
        select(CostCentreOwner).where(CostCentreOwner.user_id == user_id)
    ).all()
    return {row.cost_centre_id for row in rows}


def _can_see_key(db: Session, actor: User, key: Key) -> bool:
    """Return True if actor is the developer-owner, a CCO of the key's CC, or an admin."""
    if key.developer_id == actor.id:
        return True
    if "admin" in (actor.roles or []):
        return True
    return _is_cco_of(db, actor.id, key.cost_centre_id)


def _global_allowed_models(db: Session) -> list[str]:
    row = db.get(GlobalSetting, "allowed_models")
    if row is None:
        return []
    v = row.value
    if isinstance(v, list):
        return [str(m) for m in v]
    return []


def _rolling_spend(db: Session, key: Key, now: datetime) -> float:
    """Return the rolling-window spend for a key (invocation_log rows only).

    Returns 0.0 if ``rolling_period_days`` is not set on the key.
    """
    if key.rolling_period_days is None:
        return 0.0
    window_start = now - timedelta(days=key.rolling_period_days)
    raw = db.scalar(
        select(func.coalesce(func.sum(UsageSnapshot.cost), 0)).where(
            UsageSnapshot.key_id == key.id,
            UsageSnapshot.source == "invocation_log",
            UsageSnapshot.period_start >= window_start,
        )
    )
    return float(raw) if raw is not None else 0.0


def _serialise_key(db: Session, key: Key) -> KeyOut:
    """Build KeyOut by joining developer + cost centre and looking up inference profiles."""
    developer = db.get(User, key.developer_id)
    cc = db.get(CostCentre, key.cost_centre_id)

    # Build inference_profiles: one per model in allowed_models, skip missing.
    profiles: list[InferenceProfileRefOut] = []
    for model_id in (key.allowed_models or []):
        ip = db.scalar(
            select(InferenceProfile).where(
                InferenceProfile.cost_centre_id == key.cost_centre_id,
                InferenceProfile.model_id == model_id,
                InferenceProfile.status == "active",
            )
        )
        if ip is not None:
            profiles.append(
                InferenceProfileRefOut(
                    model_id=ip.model_id,
                    profile_arn=ip.profile_arn,
                    profile_name=ip.profile_name,
                )
            )

    now = datetime.now(timezone.utc)
    return KeyOut(
        id=key.id,
        developer_id=key.developer_id,
        developer_username=developer.username,
        developer_display_name=developer.display_name,
        cost_centre_id=key.cost_centre_id,
        cost_centre_code=cc.code,
        cost_centre_name=cc.name,
        iam_username=key.iam_username,
        status=key.status,
        allowed_models=list(key.allowed_models),
        rolling_limit=float(key.rolling_limit) if key.rolling_limit is not None else None,
        rolling_period_days=key.rolling_period_days,
        rolling_spend=_rolling_spend(db, key, now),
        lifetime_budget=float(key.lifetime_budget) if key.lifetime_budget is not None else None,
        lifetime_spend=float(key.lifetime_spend) if key.lifetime_spend is not None else 0.0,
        expires_at=key.expires_at,
        created_at=key.created_at,
        revoked_at=key.revoked_at,
        inference_profiles=profiles,
    )


def _serialise_provisioned(db: Session, key: Key, bearer_token: str) -> ProvisionedKeyOut:
    """Build ProvisionedKeyOut with the one-time bearer token for regenerate."""
    cc = db.get(CostCentre, key.cost_centre_id)

    profiles: list[InferenceProfileRefOut] = []
    for model_id in (key.allowed_models or []):
        ip = db.scalar(
            select(InferenceProfile).where(
                InferenceProfile.cost_centre_id == key.cost_centre_id,
                InferenceProfile.model_id == model_id,
                InferenceProfile.status == "active",
            )
        )
        if ip is not None:
            profiles.append(
                InferenceProfileRefOut(
                    model_id=ip.model_id,
                    profile_arn=ip.profile_arn,
                    profile_name=ip.profile_name,
                )
            )

    return ProvisionedKeyOut(
        id=key.id,
        cost_centre_id=key.cost_centre_id,
        cost_centre_code=cc.code,
        iam_username=key.iam_username,
        status=key.status,
        allowed_models=list(key.allowed_models),
        rolling_limit=float(key.rolling_limit) if key.rolling_limit is not None else None,
        rolling_period_days=key.rolling_period_days,
        lifetime_budget=float(key.lifetime_budget) if key.lifetime_budget is not None else None,
        expires_at=key.expires_at,
        bearer_token=bearer_token,
        inference_profiles=profiles,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[KeyOut])
def list_keys(
    status_filter: str | None = Query(default=None, alias="status"),
    cost_centre_id: uuid.UUID | None = Query(default=None),
    developer_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> list[KeyOut]:
    """List keys visible to the current user, with optional filters.

    - Developer: own keys only.
    - CCO: own keys + keys for cost centres they own.
    - Admin: all keys.
    Ordered by created_at desc.
    """
    is_admin = "admin" in (actor.roles or [])
    is_cco = "cco" in (actor.roles or [])

    stmt = select(Key).order_by(Key.created_at.desc())

    if status_filter is not None:
        stmt = stmt.where(Key.status == status_filter)
    if cost_centre_id is not None:
        stmt = stmt.where(Key.cost_centre_id == cost_centre_id)
    if developer_id is not None:
        stmt = stmt.where(Key.developer_id == developer_id)

    rows = db.scalars(stmt).all()

    if is_admin:
        visible = list(rows)
    else:
        cc_ids: set[uuid.UUID] = set()
        if is_cco:
            cc_ids = _owned_cc_ids(db, actor.id)
        visible = [
            k for k in rows
            if k.developer_id == actor.id or k.cost_centre_id in cc_ids
        ]

    return [_serialise_key(db, k) for k in visible]


@router.get("/{key_id}", response_model=KeyOut)
def get_key(
    key_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> KeyOut:
    """Fetch a single key (404 if not found or not visible to the caller)."""
    key = db.get(Key, key_id)
    if key is None or not _can_see_key(db, actor, key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Key not found"
        )
    return _serialise_key(db, key)


@router.post("/{key_id}/revoke", response_model=KeyOut)
def revoke_key(
    key_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    aws: AwsService = Depends(get_aws_service),
) -> KeyOut:
    """Revoke a key (dev-owner, CCO-of-cc, or admin).

    Callers outside the visible set get 404; within the visible set everyone
    allowed to see is also allowed to revoke (there is no see-but-not-revoke
    middle ground for this action).
    """
    key = db.get(Key, key_id)
    if key is None or not _can_see_key(db, actor, key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Key not found"
        )

    if key.status not in {"active", "stopped"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Key cannot be revoked (current status: {key.status!r})",
        )

    try:
        aws.revoke_key(iam_username=key.iam_username, credential_id=key.credential_id)
    except KeyNotFoundError:
        pass  # idempotent — already gone on the AWS side

    now = datetime.now(timezone.utc)
    key.status = "revoked"
    key.revoked_at = now

    record_audit(
        db,
        actor_id=actor.id,
        action="key.revoked",
        entity_type="key",
        entity_id=key.id,
        new_values={"status": "revoked", "revoked_at": now},
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(key)
    return _serialise_key(db, key)


@router.post("/{key_id}/regenerate", response_model=ProvisionedKeyOut)
def regenerate_key(
    key_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    aws: AwsService = Depends(get_aws_service),
) -> ProvisionedKeyOut:
    """Regenerate the bearer token for a key (dev-owner or admin only).

    A CCO who can see the key but is not the developer-owner and is not an
    admin gets 403, not 404.
    """
    is_admin = "admin" in (actor.roles or [])
    is_owner = False
    key = db.get(Key, key_id)

    if key is not None:
        is_owner = key.developer_id == actor.id

    # 404 if not visible at all; 403 if visible but not owner/admin
    if key is None or not _can_see_key(db, actor, key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Key not found"
        )
    if not is_owner and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    if key.status not in {"active", "stopped"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Key cannot be regenerated (current status: {key.status!r})",
        )

    try:
        new_token = aws.reset_key(credential_id=key.credential_id)
    except AwsServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AWS error: {exc}"
        ) from exc

    record_audit(
        db,
        actor_id=actor.id,
        action="key.regenerated",
        entity_type="key",
        entity_id=key.id,
        new_values={"credential_id": key.credential_id},
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(key)
    return _serialise_provisioned(db, key, new_token)


@router.patch("/{key_id}/constraints", response_model=KeyOut)
def update_constraints(
    key_id: uuid.UUID,
    body: KeyConstraintsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    aws: AwsService = Depends(get_aws_service),
) -> KeyOut:
    """Update constraints on a key (CCO-of-cc or admin only).

    Dev-owner who is not CCO/admin → 403; not visible at all → 404.
    """
    is_admin = "admin" in (actor.roles or [])
    key = db.get(Key, key_id)

    if key is None or not _can_see_key(db, actor, key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Key not found"
        )

    # Must be CCO of this CC or admin
    is_cco_of_cc = _is_cco_of(db, actor.id, key.cost_centre_id)
    if not is_admin and not is_cco_of_cc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    if key.status not in {"active", "stopped"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Constraints cannot be updated (current status: {key.status!r})",
        )

    old_values: dict = {}
    new_values: dict = {}

    # --- allowed_models ---
    if body.allowed_models is not None:
        global_models = _global_allowed_models(db)
        invalid = set(body.allowed_models) - set(global_models)
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Requested models not in globally allowed set: "
                    f"{sorted(invalid)}"
                ),
            )

        if set(body.allowed_models) != set(key.allowed_models or []):
            old_values["allowed_models"] = list(key.allowed_models or [])
            new_values["allowed_models"] = body.allowed_models

            # Ensure an active inference profile exists for each NEW model
            created_profile_arns: list[str] = []
            try:
                for model_id in body.allowed_models:
                    existing = db.scalar(
                        select(InferenceProfile).where(
                            InferenceProfile.cost_centre_id == key.cost_centre_id,
                            InferenceProfile.model_id == model_id,
                            InferenceProfile.status == "active",
                        )
                    )
                    if existing is None:
                        ref = aws.create_inference_profile(
                            cost_centre_code=db.get(CostCentre, key.cost_centre_id).code,
                            model_id=model_id,
                        )
                        created_profile_arns.append(ref.profile_arn)
                        db.add(
                            InferenceProfile(
                                cost_centre_id=key.cost_centre_id,
                                model_id=model_id,
                                profile_arn=ref.profile_arn,
                                profile_name=ref.profile_name,
                                status="active",
                            )
                        )
                        db.flush()

                aws.update_model_policy(
                    iam_username=key.iam_username,
                    allowed_models=body.allowed_models,
                )
            except AwsServiceError as exc:
                # Best-effort compensate newly created profiles, then propagate
                compensate_aws(
                    aws,
                    created_profile_arns=created_profile_arns,
                    credential_id=None,
                    iam_username=None,
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"AWS error: {exc}",
                ) from exc

            key.allowed_models = body.allowed_models

    # --- budget/period fields ---
    if body.rolling_limit is not None:
        old_values["rolling_limit"] = float(key.rolling_limit) if key.rolling_limit is not None else None
        new_values["rolling_limit"] = body.rolling_limit
        key.rolling_limit = body.rolling_limit

    if body.rolling_period_days is not None:
        old_values["rolling_period_days"] = key.rolling_period_days
        new_values["rolling_period_days"] = body.rolling_period_days
        key.rolling_period_days = body.rolling_period_days

    if body.lifetime_budget is not None:
        old_values["lifetime_budget"] = float(key.lifetime_budget) if key.lifetime_budget is not None else None
        new_values["lifetime_budget"] = body.lifetime_budget
        key.lifetime_budget = body.lifetime_budget

    # --- expiry_days ---
    if body.expiry_days is not None:
        old_expires = key.expires_at
        new_expires = datetime.now(timezone.utc) + timedelta(days=body.expiry_days)
        old_values["expires_at"] = old_expires
        new_values["expires_at"] = new_expires
        key.expires_at = new_expires

    record_audit(
        db,
        actor_id=actor.id,
        action="key.constraints_updated",
        entity_type="key",
        entity_id=key.id,
        old_values=old_values if old_values else None,
        new_values=new_values if new_values else None,
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(key)
    return _serialise_key(db, key)


@router.get("/{key_id}/usage", response_model=KeyUsageOut)
def get_key_usage(
    key_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> KeyUsageOut:
    """Return usage snapshots and spend summary for a key.

    Scoped via ``_can_see_key``: 404 if not found or not visible.
    Returns invocation_log snapshots only (most recent 200), ordered
    period_start desc.
    """
    key = db.get(Key, key_id)
    if key is None or not _can_see_key(db, actor, key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Key not found"
        )

    now = datetime.now(timezone.utc)
    rolling_spend = _rolling_spend(db, key, now)

    snapshots_rows = db.scalars(
        select(UsageSnapshot)
        .where(
            UsageSnapshot.key_id == key.id,
            UsageSnapshot.source == "invocation_log",
        )
        .order_by(UsageSnapshot.period_start.desc())
        .limit(200)
    ).all()

    snapshots = [
        UsageSnapshotOut(
            period_start=s.period_start,
            period_end=s.period_end,
            model_id=s.model_id,
            input_tokens=s.input_tokens,
            output_tokens=s.output_tokens,
            cache_read_tokens=s.cache_read_tokens,
            cache_write_tokens=s.cache_write_tokens,
            cost=float(s.cost),
        )
        for s in snapshots_rows
    ]

    return KeyUsageOut(
        key_id=key.id,
        status=key.status,
        rolling_limit=float(key.rolling_limit) if key.rolling_limit is not None else None,
        rolling_period_days=key.rolling_period_days,
        rolling_spend=rolling_spend,
        lifetime_budget=float(key.lifetime_budget) if key.lifetime_budget is not None else None,
        lifetime_spend=float(key.lifetime_spend) if key.lifetime_spend is not None else 0.0,
        snapshots=snapshots,
    )
