"""Deterministic, clock-injected usage simulator for the AWS mock layer.

The :class:`UsageSimulator` is the engine behind the mock's two usage paths
(design-decisions #2/#12): CloudWatch CC-per-model token counts
(:meth:`profile_usage`) and per-IAM-user invocation logs
(:meth:`key_usage_since`). It accrues *realistic* usage that grows over time so
dashboards and budget enforcement behave like production.

Design properties:
- **Deterministic:** each key's burn rate is derived from a stable hash of its
  credential_id, so a given key always accrues at the same reproducible rate.
- **Clock-injected:** the only source of "now" is the injected ``clock``; there
  is no wall-clock read and no randomness at query time.
- **Pause/resume aware:** active-seconds are integrated over a transition
  timeline, so a disabled key stops accruing and resumes cleanly on enable.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from app.services.aws.base import KeyUsage, TokenUsage

# Fixed plausible token split for Claude Code traffic (cache-read heavy).
# ASSUMPTION pending tech-spike #2/#3 — real ratios come from invocation logs.
_INPUT_FRACTION = 0.25
_OUTPUT_FRACTION = 0.15
_CACHE_READ_FRACTION = 0.55
_CACHE_WRITE_FRACTION = 0.05


def _rate_factor(credential_id: str) -> float:
    """Stable per-key multiplier in ``[0.5, 1.5]`` from a hash of the id."""
    digest = hashlib.sha256(credential_id.encode()).hexdigest()
    return 0.5 + (int(digest, 16) % 1000) / 1000.0


@dataclass
class _KeyRecord:
    """In-memory accrual state for a single provisioned key."""

    iam_username: str
    cost_centre_code: str
    model_profiles: dict[str, str]
    rate_per_min: float
    provisioned_at: datetime
    active: bool
    last_transition: datetime
    accrued_active_seconds: float
    # Append-only timeline of (timestamp, active_after) starting at provisioned_at.
    transitions: list[tuple[datetime, bool]] = field(default_factory=list)


class UsageSimulator:
    """Pure, deterministic accrual engine keyed by credential_id."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        base_tokens_per_minute: int = 8000,
    ) -> None:
        self._clock = clock
        self._base_tokens_per_minute = base_tokens_per_minute
        self._keys: dict[str, _KeyRecord] = {}

    # -- registration / lifecycle ------------------------------------------

    def register_key(
        self,
        *,
        credential_id: str,
        iam_username: str,
        cost_centre_code: str,
        model_profiles: dict[str, str],
        provisioned_at: datetime,
    ) -> None:
        """Begin accruing usage for a key (active from ``provisioned_at``)."""
        self._keys[credential_id] = _KeyRecord(
            iam_username=iam_username,
            cost_centre_code=cost_centre_code,
            model_profiles=dict(model_profiles),
            rate_per_min=self._base_tokens_per_minute * _rate_factor(credential_id),
            provisioned_at=provisioned_at,
            active=True,
            last_transition=provisioned_at,
            accrued_active_seconds=0.0,
            transitions=[(provisioned_at, True)],
        )

    def set_key_state(
        self, *, credential_id: str, active: bool, at: datetime
    ) -> None:
        """Pause or resume accrual, folding elapsed active time into the total."""
        rec = self._keys.get(credential_id)
        if rec is None or rec.active == active:
            return
        if rec.active:
            rec.accrued_active_seconds += (at - rec.last_transition).total_seconds()
        rec.active = active
        rec.last_transition = at
        rec.transitions.append((at, active))

    def remove_key(self, *, credential_id: str) -> None:
        """Drop a key's record (no-op if absent)."""
        self._keys.pop(credential_id, None)

    # -- accrual maths ------------------------------------------------------

    def _active_seconds_through(self, rec: _KeyRecord, t: datetime) -> float:
        """Active-seconds accrued from ``provisioned_at`` up to ``t``.

        Integrates each active interval of the transition timeline intersected
        with ``[provisioned_at, t]``. Non-decreasing in ``t`` and flat while the
        key is inactive.
        """
        if t <= rec.provisioned_at:
            return 0.0
        total = 0.0
        transitions = rec.transitions
        for idx, (ts, active_after) in enumerate(transitions):
            if not active_after:
                continue
            interval_end = (
                transitions[idx + 1][0]
                if idx + 1 < len(transitions)
                else t
            )
            interval_end = min(interval_end, t)
            if interval_end > ts:
                total += (interval_end - ts).total_seconds()
        return total

    def _window_tokens(
        self, rec: _KeyRecord, start: datetime, end: datetime
    ) -> float:
        """Total tokens accrued by ``rec`` over the window ``[start, end]``."""
        window_seconds = self._active_seconds_through(
            rec, end
        ) - self._active_seconds_through(rec, start)
        if window_seconds <= 0:
            return 0.0
        return rec.rate_per_min / 60.0 * window_seconds

    @staticmethod
    def _split(total: float) -> TokenUsage:
        """Split a non-negative token total into the fixed category ratios."""
        total = max(total, 0.0)
        return TokenUsage(
            input_tokens=int(total * _INPUT_FRACTION),
            output_tokens=int(total * _OUTPUT_FRACTION),
            cache_read_tokens=int(total * _CACHE_READ_FRACTION),
            cache_write_tokens=int(total * _CACHE_WRITE_FRACTION),
        )

    # -- query paths --------------------------------------------------------

    def profile_usage(
        self, *, profile_arn: str, start: datetime, end: datetime
    ) -> TokenUsage:
        """CloudWatch CC-per-model path: aggregate usage for a profile ARN.

        A key's burn is split evenly across its allowed models (one profile per
        model), so a multi-model key contributes only its per-model share here —
        keeping this path consistent with :meth:`key_usage_since` (no
        double-counting of a key's total across its models).
        """
        total = 0.0
        for rec in self._keys.values():
            n = len(rec.model_profiles)
            if n and profile_arn in rec.model_profiles.values():
                total += self._window_tokens(rec, start, end) / n
        return self._split(total)

    def key_usage_since(self, *, since: datetime) -> list[KeyUsage]:
        """Invocation-log path: per-key, per-model usage from ``since`` to now.

        A key's window burn is divided evenly across its models so the per-key
        total (summed over its models) equals the single window burn.
        """
        now = self._clock()
        results: list[KeyUsage] = []
        for credential_id, rec in self._keys.items():
            n = len(rec.model_profiles)
            if not n:
                continue
            per_model = self._window_tokens(rec, since, now) / n
            for model_id in rec.model_profiles:
                usage = self._split(per_model)
                if usage.total_tokens <= 0:
                    continue
                results.append(
                    KeyUsage(
                        credential_id=credential_id,
                        iam_username=rec.iam_username,
                        model_id=model_id,
                        usage=usage,
                    )
                )
        return results
