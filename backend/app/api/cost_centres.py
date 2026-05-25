"""Cost-centre management endpoints (Phase 3).

Mounted under ``/api`` → ``/api/cost-centres``. Admin-only for mutations;
listing/reading is open to any authenticated user (with archived cost centres
hidden from non-admins). First feature to write the ``audit_log``.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.deps import get_current_user, require_roles
from app.core.request import client_ip as _client_ip
from app.db.session import get_db
from app.models.cost_centre import CostCentre as CostCentreModel
from app.models.cost_centre_owner import CostCentreOwner
from app.models.inference_profile import InferenceProfile
from app.models.key import Key
from app.models.key_request import KeyRequest
from app.models.usage_snapshot import UsageSnapshot
from app.models.user import User
from app.schemas.cost_centre import (
    CostCentre,
    CostCentreCreate,
    CostCentreUpdate,
    OwnerAssign,
    OwnerSummary,
    RequestDefaults,
)
from app.schemas.usage import CcKeyUsageSummary, CcUsageOut, ModelUsageSummary
from app.services.aws import AwsService, KeyNotFoundError, get_aws_service

router = APIRouter(prefix="/cost-centres", tags=["cost-centres"])


def _serialise(db: Session, cc: CostCentreModel) -> CostCentre:
    """Build the full response shape, joining owners → users for display."""
    rows = db.execute(
        select(CostCentreOwner, User)
        .join(User, User.id == CostCentreOwner.user_id)
        .where(CostCentreOwner.cost_centre_id == cc.id)
        .order_by(CostCentreOwner.assigned_at)
    ).all()
    owners = [
        OwnerSummary(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            assigned_at=owner.assigned_at,
        )
        for owner, user in rows
    ]
    return CostCentre(
        id=cc.id,
        code=cc.code,
        name=cc.name,
        description=cc.description,
        status=cc.status,
        budget_cap=cc.budget_cap,
        request_defaults=cc.request_defaults,
        created_by=cc.created_by,
        created_at=cc.created_at,
        updated_at=cc.updated_at,
        owners=owners,
    )


def _get_cc_or_404(db: Session, cc_id: uuid.UUID) -> CostCentreModel:
    cc = db.get(CostCentreModel, cc_id)
    if cc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Cost centre not found"
        )
    return cc


@router.post("", response_model=CostCentre, status_code=status.HTTP_201_CREATED)
def create_cost_centre(
    body: CostCentreCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin")),
) -> CostCentre:
    """Create a cost centre (admin only). Duplicate ``code`` → 409."""
    existing = db.scalar(
        select(CostCentreModel).where(CostCentreModel.code == body.code)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A cost centre with that code already exists",
        )

    cc = CostCentreModel(
        code=body.code,
        name=body.name,
        description=body.description,
        budget_cap=body.budget_cap,
        request_defaults=(
            body.request_defaults.model_dump(mode="json", exclude_none=True)
            if body.request_defaults
            else None
        ),
        status="active",
        created_by=actor.id,
    )
    db.add(cc)
    db.flush()

    record_audit(
        db,
        actor_id=actor.id,
        action="cost_centre.created",
        entity_type="cost_centre",
        entity_id=cc.id,
        new_values={
            "code": cc.code,
            "name": cc.name,
            "description": cc.description,
            "budget_cap": cc.budget_cap,
            "status": cc.status,
        },
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(cc)
    return _serialise(db, cc)


@router.get("", response_model=list[CostCentre])
def list_cost_centres(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CostCentre]:
    """List cost centres ordered by code. Non-admins see active ones only."""
    stmt = select(CostCentreModel).order_by(CostCentreModel.code)
    if "admin" not in (user.roles or []):
        stmt = stmt.where(CostCentreModel.status == "active")
    return [_serialise(db, cc) for cc in db.scalars(stmt).all()]


@router.get("/{cc_id}", response_model=CostCentre)
def get_cost_centre(
    cc_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CostCentre:
    """Fetch a single cost centre. Archived ones are invisible to non-admins."""
    cc = _get_cc_or_404(db, cc_id)
    is_admin = "admin" in (user.roles or [])
    if cc.status != "active" and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Cost centre not found"
        )
    return _serialise(db, cc)


@router.patch("/{cc_id}", response_model=CostCentre)
def update_cost_centre(
    cc_id: uuid.UUID,
    body: CostCentreUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin")),
) -> CostCentre:
    """Partial update of name/description/budget_cap (admin only)."""
    cc = _get_cc_or_404(db, cc_id)

    fields = body.model_dump(exclude_unset=True)
    old_values: dict = {}
    new_values: dict = {}
    for field, new in fields.items():
        if field == "request_defaults" and new is not None:
            # Serialize the RequestDefaults Pydantic model to a plain dict for JSONB
            new = body.request_defaults.model_dump(mode="json", exclude_none=True) if body.request_defaults else None
        current = getattr(cc, field)
        if current != new:
            old_values[field] = current
            new_values[field] = new
            setattr(cc, field, new)

    if new_values:
        record_audit(
            db,
            actor_id=actor.id,
            action="cost_centre.updated",
            entity_type="cost_centre",
            entity_id=cc.id,
            old_values=old_values,
            new_values=new_values,
            ip_address=_client_ip(request),
        )
        db.commit()
        db.refresh(cc)
    return _serialise(db, cc)


@router.post("/{cc_id}/archive", response_model=CostCentre)
def archive_cost_centre(
    cc_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin")),
    aws: AwsService = Depends(get_aws_service),
) -> CostCentre:
    """Archive a cost centre (admin only). No-op if already archived.

    Cascade effects:
    - All pending key requests for this CC are set to rejected.
    - All active/stopped keys for this CC are revoked via AWS, then marked
      revoked in the DB (KeyNotFoundError is swallowed — key may be gone).
    """
    cc = _get_cc_or_404(db, cc_id)
    if cc.status != "archived":
        cc.status = "archived"
        now = datetime.now(timezone.utc)

        # Reject pending requests
        pending_requests = db.scalars(
            select(KeyRequest).where(
                KeyRequest.cost_centre_id == cc.id,
                KeyRequest.status == "pending",
            )
        ).all()
        for kr in pending_requests:
            kr.status = "rejected"
            kr.rejection_reason = "Cost centre archived"
            kr.reviewed_by = actor.id
            kr.reviewed_at = now
            record_audit(
                db,
                actor_id=actor.id,
                action="key.rejected",
                entity_type="key_request",
                entity_id=kr.id,
                new_values={
                    "status": "rejected",
                    "rejection_reason": "Cost centre archived",
                    "reviewed_by": actor.id,
                },
                ip_address=_client_ip(request),
            )

        # Revoke active/stopped keys and tear down unclaimed ('ready') identities
        active_keys = db.scalars(
            select(Key).where(
                Key.cost_centre_id == cc.id,
                Key.status.in_(["active", "stopped", "ready"]),
            )
        ).all()
        for key in active_keys:
            try:
                if key.credential_id is not None:
                    aws.revoke_key(
                        iam_username=key.iam_username,
                        credential_id=key.credential_id,
                    )
                else:
                    aws.delete_key_identity(iam_username=key.iam_username)
            except KeyNotFoundError:
                pass  # already gone on the AWS side — still mark revoked
            key.status = "revoked"
            key.revoked_at = now
            record_audit(
                db,
                actor_id=actor.id,
                action="key.revoked",
                entity_type="key",
                entity_id=key.id,
                new_values={
                    "status": "revoked",
                    "reason": "Cost centre archived",
                },
                ip_address=_client_ip(request),
            )

        record_audit(
            db,
            actor_id=actor.id,
            action="cost_centre.archived",
            entity_type="cost_centre",
            entity_id=cc.id,
            ip_address=_client_ip(request),
        )
        db.commit()
        db.refresh(cc)
    return _serialise(db, cc)


@router.post("/{cc_id}/unarchive", response_model=CostCentre)
def unarchive_cost_centre(
    cc_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin")),
) -> CostCentre:
    """Reactivate an archived cost centre (admin only). No-op if active."""
    cc = _get_cc_or_404(db, cc_id)
    if cc.status != "active":
        cc.status = "active"
        record_audit(
            db,
            actor_id=actor.id,
            action="cost_centre.unarchived",
            entity_type="cost_centre",
            entity_id=cc.id,
            ip_address=_client_ip(request),
        )
        db.commit()
        db.refresh(cc)
    return _serialise(db, cc)


@router.post("/{cc_id}/owners", response_model=CostCentre)
def assign_owner(
    cc_id: uuid.UUID,
    body: OwnerAssign,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin")),
) -> CostCentre:
    """Assign a CCO to a cost centre and grant the ``cco`` role (admin only)."""
    cc = _get_cc_or_404(db, cc_id)

    target = db.get(User, body.user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    existing = db.scalar(
        select(CostCentreOwner).where(
            CostCentreOwner.cost_centre_id == cc.id,
            CostCentreOwner.user_id == target.id,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already an owner of this cost centre",
        )

    db.add(
        CostCentreOwner(
            cost_centre_id=cc.id,
            user_id=target.id,
            assigned_by=actor.id,
        )
    )

    # Grant cco role by reassigning the list (ARRAY mutation is not tracked).
    if "cco" not in (target.roles or []):
        target.roles = [*(target.roles or []), "cco"]

    record_audit(
        db,
        actor_id=actor.id,
        action="cco.assigned",
        entity_type="cost_centre_owner",
        entity_id=cc.id,
        new_values={"cost_centre_id": cc.id, "user_id": target.id},
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(cc)
    return _serialise(db, cc)


@router.delete("/{cc_id}/owners/{user_id}", response_model=CostCentre)
def remove_owner(
    cc_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin")),
) -> CostCentre:
    """Remove a CCO from a cost centre; strip ``cco`` role if they own none."""
    cc = _get_cc_or_404(db, cc_id)

    mapping = db.scalar(
        select(CostCentreOwner).where(
            CostCentreOwner.cost_centre_id == cc.id,
            CostCentreOwner.user_id == user_id,
        )
    )
    if mapping is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Owner mapping not found",
        )

    db.delete(mapping)
    db.flush()

    remaining = db.scalar(
        select(CostCentreOwner).where(CostCentreOwner.user_id == user_id)
    )
    if remaining is None:
        target = db.get(User, user_id)
        if target is not None and "cco" in (target.roles or []):
            target.roles = [r for r in target.roles if r != "cco"]

    record_audit(
        db,
        actor_id=actor.id,
        action="cco.removed",
        entity_type="cost_centre_owner",
        entity_id=cc.id,
        old_values={"cost_centre_id": cc.id, "user_id": user_id},
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(cc)
    return _serialise(db, cc)


# ---------------------------------------------------------------------------
# Request defaults endpoints
# ---------------------------------------------------------------------------


@router.get("/{cc_id}/defaults", response_model=RequestDefaults | None)
def get_request_defaults(
    cc_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> RequestDefaults | None:
    """Return the request defaults for a cost centre (admin or CCO-of-cc)."""
    cc = _get_cc_or_404(db, cc_id)
    is_admin = "admin" in (actor.roles or [])

    if not is_admin and not _is_cco_of(db, actor.id, cc.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    if cc.request_defaults is None:
        return None

    return RequestDefaults(**cc.request_defaults)


@router.put("/{cc_id}/defaults", response_model=CostCentre)
def set_request_defaults(
    cc_id: uuid.UUID,
    body: RequestDefaults,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CostCentre:
    """Set or replace request defaults for a cost centre (admin or CCO-of-cc)."""
    cc = _get_cc_or_404(db, cc_id)
    is_admin = "admin" in (actor.roles or [])

    if not is_admin and not _is_cco_of(db, actor.id, cc.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    old_defaults = cc.request_defaults
    new_defaults = body.model_dump(mode="json", exclude_none=True) or None
    cc.request_defaults = new_defaults

    record_audit(
        db,
        actor_id=actor.id,
        action="cc.defaults_updated",
        entity_type="cost_centre",
        entity_id=cc.id,
        old_values={"request_defaults": old_defaults},
        new_values={"request_defaults": new_defaults},
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(cc)
    return _serialise(db, cc)


def _is_cco_of(db: Session, user_id: uuid.UUID, cc_id: uuid.UUID) -> bool:
    """Return True if user_id is a CCO of cc_id."""
    row = db.scalar(
        select(CostCentreOwner).where(
            CostCentreOwner.user_id == user_id,
            CostCentreOwner.cost_centre_id == cc_id,
        )
    )
    return row is not None


@router.get("/{cc_id}/usage", response_model=CcUsageOut)
def get_cost_centre_usage(
    cc_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CcUsageOut:
    """Return usage summary for a cost centre.

    Access: admin or CCO-of-cc.
    - 404 if the CC does not exist or is invisible to the caller.
    - 403 if visible but the caller is neither admin nor CCO of this CC.

    ``total_spend`` and ``by_model`` are derived from cloudwatch snapshots
    for the CC's active inference profiles. Per-key spend comes from
    invocation_log rows.
    """
    is_admin = "admin" in (actor.roles or [])
    cc = db.get(CostCentreModel, cc_id)

    if cc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Cost centre not found"
        )

    # Non-admins cannot see archived CCs
    if cc.status != "active" and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Cost centre not found"
        )

    # Must be admin or CCO of this specific CC
    if not is_admin and not _is_cco_of(db, actor.id, cc.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    # Active inference profiles for this CC
    active_profiles = db.scalars(
        select(InferenceProfile).where(
            InferenceProfile.cost_centre_id == cc.id,
            InferenceProfile.status == "active",
        )
    ).all()
    profile_ids = [p.id for p in active_profiles]

    # Total spend from cloudwatch snapshots
    total_raw = db.scalar(
        select(func.coalesce(func.sum(UsageSnapshot.cost), 0)).where(
            UsageSnapshot.inference_profile_id.in_(profile_ids),
            UsageSnapshot.source == "cloudwatch",
        )
    ) if profile_ids else 0
    total_spend = float(total_raw) if total_raw is not None else 0.0

    # By-model breakdown from cloudwatch
    by_model_rows = []
    if profile_ids:
        model_agg = db.execute(
            select(
                UsageSnapshot.model_id,
                func.coalesce(func.sum(UsageSnapshot.cost), 0).label("cost"),
                func.coalesce(
                    func.sum(
                        UsageSnapshot.input_tokens
                        + UsageSnapshot.output_tokens
                        + UsageSnapshot.cache_read_tokens
                        + UsageSnapshot.cache_write_tokens
                    ),
                    0,
                ).label("total_tokens"),
            )
            .where(
                UsageSnapshot.inference_profile_id.in_(profile_ids),
                UsageSnapshot.source == "cloudwatch",
            )
            .group_by(UsageSnapshot.model_id)
        ).all()
        by_model_rows = [
            ModelUsageSummary(
                model_id=row.model_id,
                cost=float(row.cost),
                total_tokens=int(row.total_tokens),
            )
            for row in model_agg
        ]

    # Per-key summary
    cc_keys = db.scalars(
        select(Key).where(Key.cost_centre_id == cc.id)
    ).all()
    now = datetime.now(timezone.utc)
    key_summaries: list[CcKeyUsageSummary] = []
    for key in cc_keys:
        developer = db.get(User, key.developer_id)
        # Rolling spend
        rolling_spend = 0.0
        if key.rolling_period_days is not None:
            window_start = now - timedelta(days=key.rolling_period_days)
            rs_raw = db.scalar(
                select(func.coalesce(func.sum(UsageSnapshot.cost), 0)).where(
                    UsageSnapshot.key_id == key.id,
                    UsageSnapshot.source == "invocation_log",
                    UsageSnapshot.period_start >= window_start,
                )
            )
            rolling_spend = float(rs_raw) if rs_raw is not None else 0.0
        key_summaries.append(
            CcKeyUsageSummary(
                key_id=key.id,
                developer_username=developer.username if developer else "",
                status=key.status,
                lifetime_spend=float(key.lifetime_spend) if key.lifetime_spend is not None else 0.0,
                rolling_spend=rolling_spend,
                rolling_limit=float(key.rolling_limit) if key.rolling_limit is not None else None,
                lifetime_budget=float(key.lifetime_budget) if key.lifetime_budget is not None else None,
            )
        )

    return CcUsageOut(
        cost_centre_id=cc.id,
        cost_centre_code=cc.code,
        budget_cap=float(cc.budget_cap) if cc.budget_cap is not None else None,
        total_spend=total_spend,
        keys=key_summaries,
        by_model=by_model_rows,
    )
