"""Key request & approval workflow endpoints (Phase 5).

Mounted under ``/api`` → ``/api/key-requests``.

Roles:
- Any authenticated user may create a request (or view their own).
- CCO of the target cost centre may approve/reject (and auto-approves if
  the requester *is* the CCO).
- Admin may approve/reject any request and see all.
"""

from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.cost_centre import CostCentre
from app.models.cost_centre_owner import CostCentreOwner
from app.models.global_setting import GlobalSetting
from app.models.key import Key
from app.models.key_request import KeyRequest
from app.models.user import User
from app.schemas.key_request import (
    ApprovalConstraints,
    InferenceProfileRefOut,
    KeyRequestCreate,
    KeyRequestOut,
    KeyRequestReject,
    KeyRequestResult,
    ProvisionedKeyOut,
)
from app.services.aws import AwsService, AwsServiceError, DuplicateKeyError, get_aws_service
from app.services.provisioning import provision_for_request

router = APIRouter(prefix="/key-requests", tags=["key-requests"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str | None:
    """Return the client IP if it parses as a valid address (INET column)."""
    if request.client is None:
        return None
    try:
        ipaddress.ip_address(request.client.host)
    except ValueError:
        return None
    return request.client.host


def _is_cco_of(db: Session, user_id: uuid.UUID, cc_id: uuid.UUID) -> bool:
    """Return True if user_id owns cc_id in cost_centre_owners."""
    row = db.scalar(
        select(CostCentreOwner).where(
            CostCentreOwner.user_id == user_id,
            CostCentreOwner.cost_centre_id == cc_id,
        )
    )
    return row is not None


def _can_review(db: Session, actor: User, cc_id: uuid.UUID) -> bool:
    """Return True if actor is admin or CCO of cc_id."""
    if "admin" in (actor.roles or []):
        return True
    return _is_cco_of(db, actor.id, cc_id)


def _resolve_constraints(
    db: Session,
    overrides: ApprovalConstraints | None,
    *,
    global_allowed: list[str],
) -> dict:
    """Merge global settings with any approval-time overrides.

    Validates that overridden allowed_models is a subset of global_allowed.
    Returns a dict with keys: allowed_models, rolling_limit,
    rolling_period_days, lifetime_budget, expiry_days.
    """
    # Read global settings once
    rolling_setting_row = db.get(GlobalSetting, "default_rolling_limit")
    rolling_setting = rolling_setting_row.value if rolling_setting_row else None
    default_rolling_limit = rolling_setting.get("amount") if rolling_setting else None
    default_rolling_period_days = (
        rolling_setting.get("period_days") if rolling_setting else None
    )

    lifetime_row = db.get(GlobalSetting, "default_lifetime_budget")
    default_lifetime_budget = lifetime_row.value if lifetime_row else None

    expiry_row = db.get(GlobalSetting, "default_key_expiry_days")
    default_expiry_days = expiry_row.value if expiry_row else 90

    resolved_models = global_allowed
    resolved_rolling_limit = default_rolling_limit
    resolved_rolling_period_days = default_rolling_period_days
    resolved_lifetime_budget = default_lifetime_budget
    resolved_expiry_days = default_expiry_days

    if overrides is not None:
        if overrides.allowed_models is not None:
            invalid = set(overrides.allowed_models) - set(global_allowed)
            if invalid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Requested models not in globally allowed set: "
                        f"{sorted(invalid)}"
                    ),
                )
            resolved_models = overrides.allowed_models
        if overrides.rolling_limit is not None:
            resolved_rolling_limit = overrides.rolling_limit
        if overrides.rolling_period_days is not None:
            resolved_rolling_period_days = overrides.rolling_period_days
        if overrides.lifetime_budget is not None:
            resolved_lifetime_budget = overrides.lifetime_budget
        if overrides.expiry_days is not None:
            resolved_expiry_days = overrides.expiry_days

    return {
        "allowed_models": resolved_models,
        "rolling_limit": resolved_rolling_limit,
        "rolling_period_days": resolved_rolling_period_days,
        "lifetime_budget": resolved_lifetime_budget,
        "expiry_days": int(resolved_expiry_days),
    }


def _serialise_request(db: Session, kr: KeyRequest) -> KeyRequestOut:
    """Build KeyRequestOut, joining developer + cost centre."""
    developer = db.get(User, kr.developer_id)
    cc = db.get(CostCentre, kr.cost_centre_id)
    return KeyRequestOut(
        id=kr.id,
        developer_id=kr.developer_id,
        developer_username=developer.username,
        developer_display_name=developer.display_name,
        cost_centre_id=kr.cost_centre_id,
        cost_centre_code=cc.code,
        cost_centre_name=cc.name,
        status=kr.status,
        justification=kr.justification,
        rejection_reason=kr.rejection_reason,
        reviewed_by=kr.reviewed_by,
        reviewed_at=kr.reviewed_at,
        approved_constraints=kr.approved_constraints,
        created_at=kr.created_at,
        updated_at=kr.updated_at,
    )


def _serialise_key(
    db: Session,
    key: Key,
    bearer_token: str,
    profile_refs: list[InferenceProfileRefOut],
) -> ProvisionedKeyOut:
    """Build ProvisionedKeyOut with the one-time bearer token."""
    cc = db.get(CostCentre, key.cost_centre_id)
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
        inference_profiles=profile_refs,
    )


def _get_global_allowed_models(db: Session) -> list[str]:
    row = db.get(GlobalSetting, "allowed_models")
    if row is None:
        return []
    v = row.value
    if isinstance(v, list):
        return [str(m) for m in v]
    return []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=KeyRequestResult, status_code=status.HTTP_201_CREATED)
def create_key_request(
    body: KeyRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    aws: AwsService = Depends(get_aws_service),
) -> KeyRequestResult:
    """Submit a key request for a cost centre.

    If the requester is a CCO of that cost centre, the request is
    auto-approved and a key is provisioned inline.
    """
    # Validate CC exists and is visible
    cc = db.get(CostCentre, body.cost_centre_id)
    is_admin = "admin" in (actor.roles or [])
    if cc is None or (cc.status != "active" and not is_admin):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Cost centre not found"
        )

    # 409: dev already has an active/stopped key for this CC
    existing_key = db.scalar(
        select(Key).where(
            Key.developer_id == actor.id,
            Key.cost_centre_id == cc.id,
            Key.status.in_(["active", "stopped"]),
        )
    )
    if existing_key is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active key for this cost centre",
        )

    # 409: dev already has a pending request for this CC
    existing_request = db.scalar(
        select(KeyRequest).where(
            KeyRequest.developer_id == actor.id,
            KeyRequest.cost_centre_id == cc.id,
            KeyRequest.status == "pending",
        )
    )
    if existing_request is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a pending request for this cost centre",
        )

    # Create the request row
    kr = KeyRequest(
        developer_id=actor.id,
        cost_centre_id=cc.id,
        status="pending",
        justification=body.justification,
    )
    db.add(kr)
    db.flush()

    record_audit(
        db,
        actor_id=actor.id,
        action="key.requested",
        entity_type="key_request",
        entity_id=kr.id,
        new_values={
            "developer_id": actor.id,
            "cost_centre_id": cc.id,
            "justification": body.justification,
        },
        ip_address=_client_ip(request),
    )

    # Auto-approve if requester is a CCO of this cost centre
    is_cco_of_cc = _is_cco_of(db, actor.id, cc.id)
    if is_cco_of_cc:
        global_models = _get_global_allowed_models(db)
        constraints = _resolve_constraints(db, None, global_allowed=global_models)

        now = datetime.now(timezone.utc)
        kr.status = "approved"
        kr.reviewed_by = actor.id
        kr.reviewed_at = now
        kr.approved_constraints = constraints
        db.flush()

        record_audit(
            db,
            actor_id=actor.id,
            action="key.approved",
            entity_type="key_request",
            entity_id=kr.id,
            new_values={"status": "approved", "reviewed_by": actor.id},
            ip_address=_client_ip(request),
        )

        try:
            key, bearer_token, profile_refs = provision_for_request(
                db,
                aws,
                key_request=kr,
                constraints=constraints,
                actor=actor,
                ip_address=_client_ip(request),
            )
        except DuplicateKeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except AwsServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AWS error: {exc}",
            ) from exc

        db.commit()
        db.refresh(kr)
        db.refresh(key)

        return KeyRequestResult(
            request=_serialise_request(db, kr),
            key=_serialise_key(db, key, bearer_token, profile_refs),
        )

    db.commit()
    db.refresh(kr)
    return KeyRequestResult(
        request=_serialise_request(db, kr),
        key=None,
    )


@router.get("", response_model=list[KeyRequestOut])
def list_key_requests(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> list[KeyRequestOut]:
    """List key requests visible to the current user.

    - Developer: own requests only.
    - CCO: own requests + requests targeting their cost centres.
    - Admin: all requests.
    Ordered by created_at desc.
    """
    is_admin = "admin" in (actor.roles or [])
    is_cco = "cco" in (actor.roles or [])

    stmt = select(KeyRequest).order_by(KeyRequest.created_at.desc())

    if status_filter is not None:
        stmt = stmt.where(KeyRequest.status == status_filter)

    rows = db.scalars(stmt).all()

    # Scope to visible requests
    if is_admin:
        visible = list(rows)
    else:
        # Collect CCs this user owns
        owned_cc_ids: set[uuid.UUID] = set()
        if is_cco:
            owned_cc_ids = {
                row.cost_centre_id
                for row in db.scalars(
                    select(CostCentreOwner).where(
                        CostCentreOwner.user_id == actor.id
                    )
                ).all()
            }
        visible = [
            kr
            for kr in rows
            if kr.developer_id == actor.id or kr.cost_centre_id in owned_cc_ids
        ]

    return [_serialise_request(db, kr) for kr in visible]


@router.get("/{request_id}", response_model=KeyRequestOut)
def get_key_request(
    request_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> KeyRequestOut:
    """Fetch a single key request (404 if not found or not visible)."""
    kr = db.get(KeyRequest, request_id)
    if kr is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Key request not found"
        )

    is_admin = "admin" in (actor.roles or [])
    if not is_admin:
        if kr.developer_id != actor.id and not _is_cco_of(db, actor.id, kr.cost_centre_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Key request not found"
            )

    return _serialise_request(db, kr)


@router.post("/{request_id}/approve", response_model=KeyRequestResult)
def approve_key_request(
    request_id: uuid.UUID,
    body: ApprovalConstraints,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    aws: AwsService = Depends(get_aws_service),
) -> KeyRequestResult:
    """Approve a pending key request (admin or CCO of the target CC).

    Resolves constraints (applying any overrides), provisions inference
    profiles and a key, marks the request approved.
    """
    kr = db.get(KeyRequest, request_id)
    if kr is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Key request not found"
        )

    if not _can_review(db, actor, kr.cost_centre_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    if kr.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request is not pending (current status: {kr.status!r})",
        )

    # 409 if dev already has active/stopped key for this CC
    existing_key = db.scalar(
        select(Key).where(
            Key.developer_id == kr.developer_id,
            Key.cost_centre_id == kr.cost_centre_id,
            Key.status.in_(["active", "stopped"]),
        )
    )
    if existing_key is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Developer already has an active key for this cost centre",
        )

    global_models = _get_global_allowed_models(db)
    constraints = _resolve_constraints(db, body, global_allowed=global_models)

    now = datetime.now(timezone.utc)
    kr.status = "approved"
    kr.reviewed_by = actor.id
    kr.reviewed_at = now
    kr.approved_constraints = constraints
    db.flush()

    record_audit(
        db,
        actor_id=actor.id,
        action="key.approved",
        entity_type="key_request",
        entity_id=kr.id,
        new_values={"status": "approved", "reviewed_by": actor.id},
        ip_address=_client_ip(request),
    )

    try:
        key, bearer_token, profile_refs = provision_for_request(
            db,
            aws,
            key_request=kr,
            constraints=constraints,
            actor=actor,
            ip_address=_client_ip(request),
        )
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except AwsServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AWS error: {exc}",
        ) from exc

    db.commit()
    db.refresh(kr)
    db.refresh(key)

    return KeyRequestResult(
        request=_serialise_request(db, kr),
        key=_serialise_key(db, key, bearer_token, profile_refs),
    )


@router.post("/{request_id}/reject", response_model=KeyRequestResult)
def reject_key_request(
    request_id: uuid.UUID,
    body: KeyRequestReject,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> KeyRequestResult:
    """Reject a pending key request (admin or CCO of the target CC)."""
    kr = db.get(KeyRequest, request_id)
    if kr is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Key request not found"
        )

    if not _can_review(db, actor, kr.cost_centre_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    if kr.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request is not pending (current status: {kr.status!r})",
        )

    now = datetime.now(timezone.utc)
    kr.status = "rejected"
    kr.rejection_reason = body.rejection_reason
    kr.reviewed_by = actor.id
    kr.reviewed_at = now
    db.flush()

    record_audit(
        db,
        actor_id=actor.id,
        action="key.rejected",
        entity_type="key_request",
        entity_id=kr.id,
        new_values={
            "status": "rejected",
            "rejection_reason": body.rejection_reason,
            "reviewed_by": actor.id,
        },
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(kr)

    return KeyRequestResult(
        request=_serialise_request(db, kr),
        key=None,
    )
