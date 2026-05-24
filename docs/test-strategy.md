# Test Strategy

Automation test strategy for the Claude Code AWS Bedrock Manager PoC. Scoped to fit the **mock-first** build (see [implementation-plan.md](implementation-plan.md)): the whole app is developed and demoed against the in-memory mock AWS layer, so the bulk of testing runs offline with no AWS account or AWS cost. Real-AWS testing arrives only in Phase 11.

## Principles

- **Test pyramid.** Many fast unit tests, fewer integration tests, fewer UI tests, a handful of E2E flows. Push coverage as low down the pyramid as practical — assert business logic in unit tests, not through the browser.
- **Mock-first, offline by default.** Levels 1–4 run entirely against `AWS_MODE=mock`. No level except the real-AWS E2E pass touches a live AWS account.
- **Each level owns distinct concerns** (see [Division of responsibility](#division-of-responsibility)) — avoid re-asserting the same logic at multiple levels.
- **Deterministic.** No reliance on wall-clock sleeps, real time, or network. Inject the clock so rolling-window and expiry logic is testable; freeze time in tests.
- **Tests are a build gate, not an afterthought.** The test suite for a phase lands with that phase, not in a later "testing phase".

## Test Levels

### Level 1 — Unit (backend)

| | |
|---|---|
| **Tools** | `pytest`, `pytest-asyncio`, `freezegun` (clock control) |
| **Scope** | Pure business logic in the service layer, in isolation — no DB, no HTTP, no AWS |
| **Runs** | Every commit; milliseconds |

Focus on the load-bearing algorithms where bugs are costly and logic is dense:

- **Cost calculation** — tokens × cached pricing across input/output/cache-read/cache-write rates.
- **Rolling-window spend** — sliding-window sum over `usage_snapshots`; boundary cases at the window edge.
- **Budget enforcement decisions** — per-key rolling limit, per-key lifetime budget, CC budget cap → correct disable/re-enable decision (decision logic only; persistence and AWS calls are integration-level).
- **"Tokens available again"** calculation ([design.md §8.1](design.md#81-tokens-available-again-calculation)).
- **Auto-approval rule** — requester who is a CCO of the target CC yields an already-`approved` request.
- **RBAC scoping** — given a role + entity, the expected visibility/permission outcome.

### Level 2 — Mock AWS layer (backend)

| | |
|---|---|
| **Tools** | `pytest` |
| **Scope** | The mock implementation of the AWS service interface (Phase 4) |
| **Runs** | Every commit |

The mock is test infrastructure for every level above it, so it needs its own tests. Verify provision → returns credential id + token once; disable/enable/reset state transitions; revoke removes state; `get_usage_metrics` accrues plausible token counts over time so keys actually approach and cross limits. The **shape and timing** of this fake usage data is the riskiest assumption in the whole mock-first approach — it must mirror what [tech-spike.md](tech-spike.md) #2/#3 confirm about real CloudWatch/invocation-log data, or UX feedback gathered against the mock won't hold against real AWS.

### Level 3 — Integration (backend API + DB)

| | |
|---|---|
| **Tools** | `pytest` + `httpx`/FastAPI `TestClient`, real **PostgreSQL** test database, `AWS_MODE=mock` |
| **Scope** | API endpoints through the full backend stack: routing, auth, validation, service layer, DB, mock AWS |
| **Runs** | Every commit (CI spins up a throwaway Postgres) |

Test against a real Postgres (not SQLite, not a mocked session) so DB-level invariants are actually exercised:

- **DB invariants** — one active key per developer per CC (partial unique index); `audit_log` append-only; auto-approval persisted with `reviewed_by`; constraints copied from `key_requests.approved_constraints` JSONB to typed `keys` columns at provisioning.
- **Alembic migrations** — migrate up from empty applies cleanly and matches the models.
- **Auth + RBAC end-to-end** — login issues JWT; protected routes reject missing/expired tokens; each role sees only its in-scope entities; login rate limiting.
- **Key lifecycle flows** — request → approve (with constraints) → provision (mock) → token returned once; reject with reason; revoke; regenerate (old token invalidated).
- **Budget enforcement loop** — drive the polling cycle against mock usage that crosses a limit → key status flips to `stopped`; advance the clock so the rolling window drops → key re-enabled. Hard stop, never throttle.
- **Audit trail** — state-changing actions write the expected `audit_log` rows.

### Level 4 — UI (frontend)

| | |
|---|---|
| **Tools** | `Vitest` + React Testing Library; `MSW` (Mock Service Worker) to stub the API |
| **Scope** | Components, hooks, and role-based rendering against a mocked API — no real backend |
| **Runs** | Every commit |

- **Component/interaction tests** — request-key form, approve modal (constraint entry), reject modal (reason required), token display (copy-to-clipboard, shown once), status badges (Active/Expired/Revoked/Stopped/Pending).
- **Role-based rendering** — developer vs CCO vs admin see the correct navigation and actions.
- **Data fetching/states** — loading, empty, and error states via MSW; TanStack Query refetch behaviour.
- **Dashboards** — charts/tables render from representative usage payloads (assert data wiring, not pixels).

### Level 5 — E2E (full stack)

End-to-end has two passes. Both drive the real browser through the running stack; they differ only in what backs the AWS layer.

| | |
|---|---|
| **Tools** | `Playwright` against the Docker Compose stack (frontend + backend + Postgres) |
| **Scope** | Critical user journeys through the real UI and a real backend |

**Pass A — against the mock (the Phase 7 clickable-prototype milestone).** The golden path, all in-browser: log in as each role → developer requests a key → CCO approves with constraints → token shown once with setup instructions → key appears on the developer dashboard → mock usage accrues → spend tracks against limits → key hard-stops when a limit or CC budget is exceeded. This guards the demo flow and runs in CI (no AWS cost). Keep it to a few high-value journeys, not exhaustive coverage.

**Pass B — against real AWS in the dev environment (post-deploy, Phase 11).** Once the real boto3 implementation is wired (`AWS_MODE=real`) and deployed to the dedicated dev AWS account, run a thin smoke suite that exercises what only real AWS can prove — things the mock cannot validate:

- Provision a key → IAM user + scoped inline policy actually created; key request approved end-to-end.
- Model restriction is enforced *at the IAM layer* — an approved model works, a disallowed model returns 403.
- Real usage path: configure Claude Code with the bearer token + CC inference-profile ARN → invoke a model → token counts surface from CloudWatch → appear on the dashboard within the polling window.
- Disable/reset: deactivating the credential stops invocation immediately; reset returns a new token and invalidates the old one.
- Revoke → IAM user + credential cleaned up.

This pass is **not** in the per-commit CI gate — it incurs AWS cost and latency. Run it on demand and before a demo, against the dev environment only. It supersedes and formalises the Phase 11 "integration test suite" and "E2E smoke test" checklist items.

## Division of responsibility

To avoid duplicating assertions across levels, each concern is owned by exactly one level:

| Concern | Owned by |
|---|---|
| Cost/rolling-window/enforcement *math* | Unit (L1) |
| Mock AWS behaviour & usage-data shape | Mock layer (L2) |
| API contract, RBAC, DB invariants, enforcement *wiring* | Integration (L3) |
| Component behaviour & role-based rendering | UI (L4) |
| Critical journeys through the real UI | E2E mock pass (L5-A) |
| Real AWS/IAM enforcement & live usage path | E2E real pass (L5-B) |

## CI gate

Per-commit / per-PR (all offline, mock-backed): **L1 + L2 + L3 + L4 + L5-A**. These must be green to merge. **L5-B** runs out-of-band against the dev environment, on demand and pre-demo. Track line coverage on the backend service layer (the highest-risk code) but treat the focused tests above as the real signal — coverage percentage is a guardrail, not a target.

## Test data & fixtures

- Reuse the Phase 2 seed roles (`admin`, `dev1`, `ccowner1`, …) as the canonical test personas across L3–L5 so fixtures match the demo.
- Backend integration tests get a fresh schema per run (migrate up, truncate between tests, or transactional rollback).
- Inject a controllable clock everywhere time matters (rolling windows, expiry, "available again") so tests are deterministic.

## Out of scope for the PoC

Load/performance testing, security penetration testing beyond the Phase 11 OWASP review, contract testing, visual-regression snapshots, and any automated testing of deferred-to-production features (SSO, email/Slack alerts, CSV export, Guardrails).

## Related documents

- [Implementation Plan](implementation-plan.md) — phased build; tests land per phase.
- [Design](design.md) — flows and algorithms the tests assert against.
- [Data Model](data-model.md) — DB invariants exercised at integration level.
- [Tech Spike](tech-spike.md) — validates the real-AWS data shape the mock must imitate.
