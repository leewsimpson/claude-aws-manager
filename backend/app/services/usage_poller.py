"""Usage poller: background poll cycle and daemon thread wrapper.

``run_poll_cycle`` is a pure function that collects usage snapshots, updates
``key.lifetime_spend``, and enforces rolling/lifetime/CC budget limits by
disabling (or re-enabling) keys as appropriate.

``UsagePoller`` wraps the cycle in a daemon thread with clean stop semantics.

``rehydrate_aws_from_db`` is a startup helper that re-populates the in-memory
AWS service state from the DB so the mock survives process restarts (and the
real service can prime any in-memory caches it may eventually maintain).
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.db.session import SessionLocal
from app.models.cost_centre import CostCentre
from app.models.inference_profile import InferenceProfile
from app.models.key import Key
from app.models.usage_snapshot import UsageSnapshot
from app.services.aws.base import AwsService, KeyNotFoundError
from app.services.pricing import compute_cost, load_pricing

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Startup rehydration
# ---------------------------------------------------------------------------


def rehydrate_aws_from_db(db: Session, aws: AwsService) -> None:
    """Re-populate the AWS service's in-memory state from the DB.

    Safe to call on every startup (methods are idempotent — skip if already
    known). Only touches active inference profiles and active/stopped keys.
    """
    # 1. Rehydrate active inference profiles
    profiles = db.scalars(
        select(InferenceProfile).where(InferenceProfile.status == "active")
    ).all()
    for profile in profiles:
        cc = db.get(CostCentre, profile.cost_centre_id)
        if cc is None:
            continue
        aws.rehydrate_profile(
            cost_centre_code=cc.code,
            model_id=profile.model_id,
            profile_arn=profile.profile_arn,
            profile_name=profile.profile_name,
        )

    # Build a map of (cost_centre_id, model_id) → profile_arn for key rehydration
    profile_map: dict[tuple[uuid.UUID, str], str] = {
        (p.cost_centre_id, p.model_id): p.profile_arn for p in profiles
    }

    # 2. Rehydrate active/stopped keys
    keys = db.scalars(
        select(Key).where(Key.status.in_(["active", "stopped"]))
    ).all()
    now = datetime.now(timezone.utc)
    for key in keys:
        model_profiles = {
            model_id: profile_map[(key.cost_centre_id, model_id)]
            for model_id in (key.allowed_models or [])
            if (key.cost_centre_id, model_id) in profile_map
        }
        aws.rehydrate_key(
            credential_id=key.credential_id,
            iam_username=key.iam_username,
            cost_centre_code=db.get(CostCentre, key.cost_centre_id).code,
            allowed_models=list(key.allowed_models or []),
            model_profiles=model_profiles,
            provisioned_at=key.created_at if key.created_at.tzinfo else key.created_at.replace(tzinfo=timezone.utc),
            active=(key.status == "active"),
        )

    # 3. Rehydrate identities for 'ready' keys (approved, token not yet retrieved)
    #    so the developer can still issue the credential after a restart.
    ready_keys = db.scalars(select(Key).where(Key.status == "ready")).all()
    for key in ready_keys:
        cc = db.get(CostCentre, key.cost_centre_id)
        if cc is None:
            continue
        aws.rehydrate_identity(
            iam_username=key.iam_username,
            cost_centre_code=cc.code,
            allowed_models=list(key.allowed_models or []),
        )


# ---------------------------------------------------------------------------
# Poll cycle
# ---------------------------------------------------------------------------


def run_poll_cycle(
    db: Session,
    aws: AwsService,
    *,
    since: datetime,
    now: datetime,
) -> dict:
    """Collect usage, update spend, and enforce budget limits.

    Pure function over the injected session and AWS service. Does NOT open
    or close the session. Returns a small summary dict.

    Steps:
    1. Load pricing.
    2. CloudWatch path: insert a UsageSnapshot per active InferenceProfile
       that has non-zero usage in [since, now].
    3. Invocation-log path: insert a UsageSnapshot per per-key/model entry
       returned by parse_invocation_logs.
    4. Flush, then update key.lifetime_spend and enforce limits.
    5. Commit.
    """
    pricing = load_pricing(db)

    cloudwatch_rows = 0
    invocation_rows = 0
    stopped_count = 0
    restarted_count = 0

    # ---- step 2: CloudWatch path -------------------------------------------
    active_profiles = db.scalars(
        select(InferenceProfile).where(InferenceProfile.status == "active")
    ).all()

    for profile in active_profiles:
        usage = aws.get_usage_metrics(
            profile_arn=profile.profile_arn, start=since, end=now
        )
        if usage.total_tokens > 0:
            cost = compute_cost(usage, pricing.get(profile.model_id))
            db.add(UsageSnapshot(
                key_id=None,
                inference_profile_id=profile.id,
                model_id=profile.model_id,
                source="cloudwatch",
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                cost=cost,
                period_start=since,
                period_end=now,
                collected_at=now,
            ))
            cloudwatch_rows += 1

    # ---- step 3: Invocation-log path ----------------------------------------
    # Build lookup: credential_id → Key
    keys_by_cred: dict[str, Key] = {}
    all_relevant_keys = db.scalars(
        select(Key).where(Key.status.in_(["active", "stopped", "revoked"]))
    ).all()
    for k in all_relevant_keys:
        keys_by_cred[k.credential_id] = k

    # Build lookup: (cost_centre_id, model_id) → InferenceProfile (active only)
    profile_lookup: dict[tuple[uuid.UUID, str], InferenceProfile] = {
        (p.cost_centre_id, p.model_id): p for p in active_profiles
    }

    key_usages = aws.parse_invocation_logs(since=since)
    for ku in key_usages:
        key = keys_by_cred.get(ku.credential_id)
        if key is None:
            continue
        profile = profile_lookup.get((key.cost_centre_id, ku.model_id))
        if profile is None:
            continue
        cost = compute_cost(ku.usage, pricing.get(ku.model_id))
        db.add(UsageSnapshot(
            key_id=key.id,
            inference_profile_id=profile.id,
            model_id=ku.model_id,
            source="invocation_log",
            input_tokens=ku.usage.input_tokens,
            output_tokens=ku.usage.output_tokens,
            cache_read_tokens=ku.usage.cache_read_tokens,
            cache_write_tokens=ku.usage.cache_write_tokens,
            cost=cost,
            period_start=since,
            period_end=now,
            collected_at=now,
        ))
        invocation_rows += 1

    # Flush so new rows are queryable in step 4
    db.flush()

    # ---- step 4: update spend + enforce limits ------------------------------
    # Compute CC-level spend from cloudwatch snapshots once per CC
    cc_spend_cache: dict[uuid.UUID, Decimal] = {}

    def _cc_spend(cc_id: uuid.UUID) -> Decimal:
        if cc_id in cc_spend_cache:
            return cc_spend_cache[cc_id]
        # All cloudwatch rows for active profiles in this CC
        cc_profile_ids = [
            p.id for p in active_profiles if p.cost_centre_id == cc_id
        ]
        if not cc_profile_ids:
            cc_spend_cache[cc_id] = Decimal("0")
            return Decimal("0")
        total = db.scalar(
            select(func.coalesce(func.sum(UsageSnapshot.cost), 0)).where(
                UsageSnapshot.inference_profile_id.in_(cc_profile_ids),
                UsageSnapshot.source == "cloudwatch",
            )
        )
        result = Decimal(str(total)) if total is not None else Decimal("0")
        cc_spend_cache[cc_id] = result
        return result

    # Only process active/stopped keys
    enforce_keys = db.scalars(
        select(Key).where(Key.status.in_(["active", "stopped"]))
    ).all()

    for key in enforce_keys:
        # Lifetime spend from invocation_log rows for this key
        lifetime_raw = db.scalar(
            select(func.coalesce(func.sum(UsageSnapshot.cost), 0)).where(
                UsageSnapshot.key_id == key.id,
                UsageSnapshot.source == "invocation_log",
            )
        )
        lifetime_spend = Decimal(str(lifetime_raw)) if lifetime_raw is not None else Decimal("0")
        key.lifetime_spend = lifetime_spend

        # Rolling spend
        rolling_spend = Decimal("0")
        if key.rolling_period_days is not None:
            window_start = now - timedelta(days=key.rolling_period_days)
            rolling_raw = db.scalar(
                select(func.coalesce(func.sum(UsageSnapshot.cost), 0)).where(
                    UsageSnapshot.key_id == key.id,
                    UsageSnapshot.source == "invocation_log",
                    UsageSnapshot.period_start >= window_start,
                )
            )
            rolling_spend = Decimal(str(rolling_raw)) if rolling_raw is not None else Decimal("0")

        # CC spend
        cc_spend = _cc_spend(key.cost_centre_id)
        cc = db.get(CostCentre, key.cost_centre_id)

        # Determine if we should stop
        should_stop = False
        reason: str | None = None

        if key.rolling_limit is not None and rolling_spend >= Decimal(str(key.rolling_limit)):
            should_stop = True
            reason = "rolling_limit_exceeded"
        elif key.lifetime_budget is not None and lifetime_spend >= Decimal(str(key.lifetime_budget)):
            should_stop = True
            reason = "lifetime_budget_exceeded"
        elif (
            cc is not None
            and cc.budget_cap is not None
            and cc_spend >= Decimal(str(cc.budget_cap))
        ):
            should_stop = True
            reason = "cc_budget_exceeded"

        if key.status == "active" and should_stop:
            try:
                aws.disable_key(credential_id=key.credential_id)
            except KeyNotFoundError:
                pass
            key.status = "stopped"
            record_audit(
                db,
                actor_id=None,
                action="key.stopped",
                entity_type="key",
                entity_id=key.id,
                new_values={
                    "reason": reason,
                    "rolling_spend": float(rolling_spend),
                    "lifetime_spend": float(lifetime_spend),
                    "cc_spend": float(cc_spend),
                },
                ip_address=None,
            )
            stopped_count += 1

        elif key.status == "stopped" and not should_stop:
            try:
                aws.enable_key(credential_id=key.credential_id)
            except KeyNotFoundError:
                pass
            key.status = "active"
            record_audit(
                db,
                actor_id=None,
                action="key.restarted",
                entity_type="key",
                entity_id=key.id,
                new_values={
                    "rolling_spend": float(rolling_spend),
                    "lifetime_spend": float(lifetime_spend),
                    "cc_spend": float(cc_spend),
                },
                ip_address=None,
            )
            restarted_count += 1

    db.commit()
    return {
        "cloudwatch_rows": cloudwatch_rows,
        "invocation_rows": invocation_rows,
        "stopped": stopped_count,
        "restarted": restarted_count,
    }


# ---------------------------------------------------------------------------
# Daemon thread wrapper
# ---------------------------------------------------------------------------


class UsagePoller:
    """Daemon thread that calls ``run_poll_cycle`` on a fixed interval.

    Usage::

        poller = UsagePoller(aws=aws, interval_seconds=120)
        poller.start()
        ...
        poller.stop()
    """

    def __init__(
        self,
        *,
        aws: AwsService,
        interval_seconds: int = 120,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        self._aws = aws
        self._interval = interval_seconds
        self._clock = clock
        self._session_factory = session_factory
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_run: datetime | None = None

    def start(self) -> None:
        """Start the background polling thread."""
        self._last_run = self._clock()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="usage-poller")
        self._thread.start()
        logger.info("UsagePoller started (interval=%ds)", self._interval)

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the thread to stop and wait briefly for it to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        logger.info("UsagePoller stopped")

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval):
            now = self._clock()
            db = self._session_factory()
            try:
                since = self._last_run or now
                summary = run_poll_cycle(db, self._aws, since=since, now=now)
                self._last_run = now
                logger.debug("Poll cycle complete: %s", summary)
            except Exception:
                logger.exception("Poll cycle failed — will retry next interval")
            finally:
                db.close()
