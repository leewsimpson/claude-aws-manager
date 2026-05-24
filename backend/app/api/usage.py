"""Platform-wide usage summary endpoint (Phase 7).

Mounted under ``/api`` → ``/api/usage``. Admin-only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.session import get_db
from app.models.cost_centre import CostCentre
from app.models.inference_profile import InferenceProfile
from app.models.key import Key
from app.models.usage_snapshot import UsageSnapshot
from app.models.user import User
from app.schemas.usage import CcUsageSummaryItem, ModelUsageSummary, UsageSummaryOut

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/summary", response_model=UsageSummaryOut)
def get_usage_summary(
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin")),
) -> UsageSummaryOut:
    """Platform-wide usage summary. Admin only.

    Totals are derived from cloudwatch snapshots. Key counts are from the
    ``keys`` table.
    """
    # Platform-wide total spend from cloudwatch
    total_raw = db.scalar(
        select(func.coalesce(func.sum(UsageSnapshot.cost), 0)).where(
            UsageSnapshot.source == "cloudwatch"
        )
    )
    total_spend = float(total_raw) if total_raw is not None else 0.0

    # Platform-wide key counts
    active_keys = db.scalar(
        select(func.count(Key.id)).where(Key.status == "active")
    ) or 0
    stopped_keys = db.scalar(
        select(func.count(Key.id)).where(Key.status == "stopped")
    ) or 0

    # Platform-wide by-model breakdown from cloudwatch
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
        .where(UsageSnapshot.source == "cloudwatch")
        .group_by(UsageSnapshot.model_id)
    ).all()
    by_model = [
        ModelUsageSummary(
            model_id=row.model_id,
            cost=float(row.cost),
            total_tokens=int(row.total_tokens),
        )
        for row in model_agg
    ]

    # Per-cost-centre summary
    cost_centres_all = db.scalars(select(CostCentre)).all()
    cc_items: list[CcUsageSummaryItem] = []
    for cc in cost_centres_all:
        # Active inference profiles for this CC
        cc_profile_ids = db.scalars(
            select(InferenceProfile.id).where(
                InferenceProfile.cost_centre_id == cc.id,
                InferenceProfile.status == "active",
            )
        ).all()
        cc_total_raw = 0
        if cc_profile_ids:
            cc_total_raw = db.scalar(
                select(func.coalesce(func.sum(UsageSnapshot.cost), 0)).where(
                    UsageSnapshot.inference_profile_id.in_(cc_profile_ids),
                    UsageSnapshot.source == "cloudwatch",
                )
            ) or 0

        cc_active = db.scalar(
            select(func.count(Key.id)).where(
                Key.cost_centre_id == cc.id,
                Key.status == "active",
            )
        ) or 0
        cc_stopped = db.scalar(
            select(func.count(Key.id)).where(
                Key.cost_centre_id == cc.id,
                Key.status == "stopped",
            )
        ) or 0

        cc_items.append(
            CcUsageSummaryItem(
                cost_centre_id=cc.id,
                code=cc.code,
                name=cc.name,
                budget_cap=float(cc.budget_cap) if cc.budget_cap is not None else None,
                total_spend=float(cc_total_raw),
                active_keys=cc_active,
                stopped_keys=cc_stopped,
            )
        )

    return UsageSummaryOut(
        total_spend=total_spend,
        active_keys=active_keys,
        stopped_keys=stopped_keys,
        cost_centres=cc_items,
        by_model=by_model,
    )
