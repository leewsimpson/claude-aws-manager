# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current State

**Phase 7 complete** — the ⭐ **clickable local prototype milestone** is reached: log in → request key → approve with constraints → token shown once → key on the developer dashboard → mock usage accrues → spend tracks rolling/lifetime limits and CC budget → key **hard-stops** when a limit is crossed (and restarts when the rolling window clears). See `docs/implementation-log.md` for detailed progress and `docs/implementation-plan.md` for what's next (**Phase 8 — dashboards & visualisations**). Monorepo: `/backend` (FastAPI), `/frontend` (React+Vite), `/docker`, root `docker-compose.yml`. DB at Alembic head `c3d4e5f6a7b8` (`request_defaults` on `cost_centres`); the only remaining deferred tables are `alert_*` → P9.

**CC request defaults & hard expiry:** cost centres now carry a `request_defaults` JSONB column storing default constraints (allowed_models, rolling_limit, rolling_period_days, lifetime_budget, expires_at) that pre-populate the approval form. `expires_at` is a **hard project-end date**, not a relative duration. Constraint resolution order: approval overrides → CC `request_defaults` → global settings. Endpoints: `GET/PUT /api/cost-centres/{id}/defaults` (admin or CCO-of-cc). The approval schema (`ApprovalConstraints`) and key constraints update (`KeyConstraintsUpdate`) now accept `expires_at` alongside `expiry_days`; `expires_at` takes precedence. Frontend: CCOs see a "Defaults" button on each CC row; the approval form pre-fills from CC defaults and uses a date picker for expiry.

**Cost tracking & enforcement (P7):** a background **usage poller** (a daemon thread, gated by `poller_enabled`; started in the FastAPI `lifespan`) runs `app/services/usage_poller.py::run_poll_cycle(db, aws, *, since, now)` — a pure, clock-injected function that pulls CloudWatch CC-level + per-key invocation-log usage from the AWS layer, writes non-overlapping-delta `usage_snapshots` (`source='cloudwatch'` with `key_id=NULL`, vs `source='invocation_log'` with `key_id` set), recomputes `keys.lifetime_spend`, and **enforces budgets**: disables (→`stopped`, audit `key.stopped`) when rolling spend ≥ `rolling_limit`, lifetime spend ≥ `lifetime_budget`, or CC cloudwatch spend ≥ `budget_cap`; re-enables (→`active`, audit `key.restarted`) when none apply. Cost = `app/services/pricing.py::compute_cost(usage, prices)` (tokens × per-1k `pricing_cache`, seeded from `PRICING`). Usage endpoints: `GET /api/keys/{id}/usage`, `GET /api/cost-centres/{id}/usage` (admin/CCO), `GET /api/usage/summary` (admin). `KeyOut` now carries live `lifetime_spend` + `rolling_spend`. The mock is in-memory, so `lifespan` calls `rehydrate_aws_from_db(...)` at startup to re-register active profiles/keys so usage survives a backend restart (no-op on `RealAwsService`).

## What This Is

A self-service web app for provisioning and governing Claude Code access via AWS Bedrock within an organisation. The platform **provisions and governs credentials but does not sit in the inference path** — developers get a bearer token (`AWS_BEARER_TOKEN_BEDROCK`) and call Bedrock directly. Three roles (a user can hold several): **Developer**, **Cost Centre Owner / CCO**, **Administrator**.

## Tech Stack

- **Backend:** Python 3.12 + FastAPI, Pydantic, SQLAlchemy + Alembic, uv. DB driver: psycopg v3.
- **Frontend:** React + Vite + TypeScript, React Router, TanStack Query.
- **Database:** PostgreSQL 16 (JSONB for policy docs / audit metadata / approval constraints).
- **Deployment:** Docker Compose locally (`backend` :8000, `frontend` :5173 proxying `/api`, `db` :5432); Docker on ECS + RDS/Aurora in production.

## Local Dev — Build & Run

```bash
docker compose up           # from repo root: db :5432, backend :8000, frontend :5173
# frontend → http://localhost:5173 ; backend health → http://localhost:8000/api/health
```

Both services bind-mount source with live reload (uvicorn `--reload`, vite dev). The backend compose `command` runs `alembic upgrade head && python -m app.seed` before uvicorn (idempotent seed). Backend-only, outside Docker: `cd backend && uv sync && uv run uvicorn app.main:app --reload`. Backend tests: `cd backend && uv run pytest` (uses a separate `claudeaws_test` DB; needs Postgres on `localhost:5432`). Frontend: `npm run build`, `npm run test` (Vitest).

**Demo acceleration (P7):** the realistic usage rate / poll interval live in `app/config.py` (`usage_tokens_per_minute=8000`, `poll_interval_seconds=120`, `poller_enabled=True`). `docker-compose.yml` overrides the backend with demo-friendly values (`USAGE_TOKENS_PER_MINUTE=8000000`, `POLL_INTERVAL_SECONDS=20`) so synthetic spend visibly crosses the default $50/7-day rolling limit in ~2 min. `scripts/p7_enforce_check.py` is a live enforcement smoke test against the running stack. The poller does **not** run under pytest (the test `client` fixture doesn't enter the `lifespan` context); enforcement is unit-tested directly via `run_poll_cycle` with an injected clock.

### Gotchas

1. **pydantic-settings list/dict fields:** must use `Annotated[list[str], NoDecode]` + a splitting validator — pydantic-settings JSON-decodes env vars before validators run.
2. **Backend deps changed:** `docker compose up -d --build --force-recreate --renew-anon-volumes backend` — the anonymous `/app/.venv` volume shadows the rebuilt venv.
3. **Alembic migrations:** generate against an **empty** schema; keep `create_all` for the test DB only.
4. **Frontend deps changed:** same anonymous-volume trap — `docker compose up -d --build --force-recreate --renew-anon-volumes frontend`.
5. **New frontend routes/pages:** `docker compose restart frontend` before browser-verifying (stale Vite module graph).
6. **git-bash path mangling:** prefix Node/CLI invocations with `MSYS_NO_PATHCONV=1` when args have leading slashes.

## Coding Patterns

These are the reusable patterns established in phases 1–6. Use them for all new work.

- **Auth:** `get_current_user` + `require_roles(*roles)` in `app/core/deps.py` — use to protect every new endpoint. Seed personas: `admin/admin`, `dev1/dev1`, `dev2/dev2`, `ccowner1/ccowner1`.
- **Audit:** `app/core/audit.py::record_audit(...)` is the single audit-log writer (handler commits); `app/core/request.py::client_ip(request)` guards the `INET` column. Use both for every state change.
- **AWS:** all ops go through `app/services/aws/AwsService` ABC; inject via `Depends(get_aws_service)`. App code **never imports `boto3`**. `AWS_MODE=mock|real` selects implementation; `RealAwsService` is a Phase-11 stub.
- **Provisioning:** `app/services/provisioning.py::provision_for_request` handles the full provisioning flow with `compensate_aws(...)` rollback on failure so AWS state never drifts from a rolled-back DB.
- **DB transactions:** `get_db` rolls back on exception — failed requests never leave a half-applied transaction.
- **Usage & budgets:** all spend flows through `usage_snapshots` (non-overlapping `[since, now]` deltas) written by `run_poll_cycle`; cost via `pricing.py::compute_cost` (money as `Decimal`). Reuse `run_poll_cycle` for any new enforcement; reuse `aws.rehydrate_*` (no-op on real AWS) when the mock needs to recover in-memory state from the DB.

**KEEP ALL DOCUMENTATION CONSISTENT, MINIMISE DUPLICATION, NOT VERBOSE.**

## Architecture — Non-Obvious Essentials

Load-bearing decisions that span multiple docs. Read `docs/design-decisions.md` for full rationale before changing any of them.

- **Credential model = Bedrock API Keys.** Each key creates a backing IAM user `claude-{developer}-{cc_code}`. Lifecycle: `CreateServiceSpecificCredential` / `Update...(Status=Inactive)` / `Reset...` / `Delete...`.
- **Bearer tokens are NEVER stored.** Returned once on provisioning/regeneration. Lost token → regenerate. Do not add token persistence.
- **Model restrictions enforced at the AWS/IAM layer**, not in the app. Inline IAM policy scopes `bedrock:InvokeModel` to approved model ARNs.
- **Inference profiles: one per cost centre per model.** CloudWatch metrics keyed per profile → CC-level token counts.
- **Cost tracking is app-calculated** (tokens × cached pricing), not AWS Cost Explorer.
- **Budget enforcement = background polling loop every 2 min.** Hard stop (key deactivated), never throttling.
- **Rolling budgets = sliding windows** of configurable days, not calendar periods.
- **AWS abstracted behind mock/real interface.** Day-to-day dev: `AWS_MODE=mock`. App code never calls `boto3` directly.
- **Region:** `ap-southeast-2` (Australia). Single region, single dedicated AWS account.

## Data Model

`docs/data-model.md` is the canonical schema reference and source of truth for SQLAlchemy models and Alembic migrations.

Key invariants:
- One active key per developer per cost centre — partial unique index on `keys(developer_id, cost_centre_id) WHERE status IN ('active','stopped')`.
- CCO auto-approval: requester who is a CCO of the target CC gets auto-approved.
- Approval constraints (`key_requests.approved_constraints` JSONB) copied to typed columns on `keys` at provisioning.
- `audit_log` is append-only; admin-only access.

## PoC Auth

Hard-coded users seeded with bcrypt hashes, JWT issued on login. SSO (OIDC/SAML) is **deferred to production**.

## Deferred to Production (do NOT build in PoC)

Email/Slack notifications, CSV export, Bedrock Guardrails, SSO auto-offboarding, drift reconciliation, usage-spike detection.

## Conventions

- **British/Australian spelling:** "cost centre", "organisation", "visualisation". AWS API names and `AWS_BEARER_TOKEN_BEDROCK` use their literal forms.
- **Frontend design system — "Bedrock Control Room":** dark-only console aesthetic; do **not** reintroduce light variants. Design tokens in `frontend/src/index.css` (`--bg`/`--bg-elev`/`--line`/`--text`/`--accent`/`--ok`/`--warn`/`--danger`); component styles in `frontend/src/App.css`. Fonts: **IBM Plex Mono** (headings, labels, code, buttons) + **IBM Plex Sans** (body). Reuse existing class vocabulary (`.panel`/`.table`/`.badge--*`/`.btn`/`.form--inline`/`.token-reveal` etc.) — no inline styles or hand-rolled colours.

## Doc Map

- `docs/requirements.md` — functional + non-functional requirements.
- `docs/design.md` — C4 diagrams, component layers, sequence flows.
- `docs/data-model.md` — canonical DB schema.
- `docs/design-decisions.md` — numbered architectural decisions with rationale.
- `docs/implementation-plan.md` — 11-phase build sequence with per-phase checklists.
- `docs/implementation-log.md` — live build progress, decisions, and per-phase retros.
- `docs/tech-spike.md` — AWS validation items.
- `docs/test-strategy.md` — test strategy (unit, integration, UI, E2E).
- `research/01`–`research/09` — supporting research.
