# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current State

**Phase 6 complete** (key management & developer dashboard) — see `docs/implementation-log.md` for live progress. Monorepo: `/backend` (FastAPI), `/frontend` (React+Vite), `/docker`, root `docker-compose.yml`. The 7 core domain tables plus **`inference_profiles`** now exist (live DB at Alembic head `a1b2c3d4e5f6`); remaining deferred tables (`usage_snapshots`/`pricing_cache` → P7, `alert_*` → P9) arrive with their phase. **Auth works:** `POST /api/auth/login` + `GET /api/auth/me` (JWT/HS256), with reusable `get_current_user` + `require_roles(*roles)` in `app/core/deps.py` — use these to protect every new endpoint. Seed personas: `admin/admin`, `dev1/dev1`, `dev2/dev2`, `ccowner1/ccowner1` (cco+developer). **Cost-centre API lives at `/api/cost-centres`** (admin CRUD + archive/unarchive + owner assign/remove; devs get an active-only read view) plus admin-only `GET /api/users`. **Archiving a CC now cascades:** pending requests auto-rejected, active/stopped keys revoked via the AWS layer. **Audit logging is live:** reusable `app/core/audit.py::record_audit(...)` is the single audit-log writer — it `db.add`s a row (the handler commits), coerces values to JSON, and the shared `app/core/request.py::client_ip(request)` helper guards the `INET` column; reuse both for every future state change. `get_db` rolls back on exception (so failed requests never leave a half-applied transaction). Assigning/removing a CCO auto-grants/strips the `cco` role. **AWS layer is live (mock only):** all AWS ops sit behind `app/services/aws/AwsService` (ABC in `base.py`); `MockAwsService` keeps key/profile state in-memory and drives a deterministic `UsageSimulator` for synthetic CloudWatch/invocation-log usage; `RealAwsService` is a Phase-11 `NotImplementedError` stub. **App code never imports `boto3`** — always go through `get_aws_service()` (an `@lru_cache` singleton, injected via `Depends(get_aws_service)`; routes on `AWS_MODE=mock|real`). `build_model_policy(allowed_models)` builds the exact-ARN IAM policy (Decision #3/#13). ⚠ The tech-spike "validate before you mock" items were **not** run (offline, no AWS account) — the synthetic-usage *shape* is a documented assumption isolated in `usage.py`, to be reconciled in Phase 11. **Key request & approval flow lives at `/api/key-requests`** (`POST` create / `GET` scoped list / `GET {id}` / `POST {id}/approve` / `POST {id}/reject`), returning a `{request, key}` envelope. **Provision-on-approval, token shown once:** the bearer token rides `ProvisionedKey.bearer_token` in the approve/auto-approve response only — never persisted, never in lists (Decision #10, no token column). Auto-approval fires when the requester is a CCO of the target CC (resolving `global_settings` defaults). Provisioning order lives in `app/services/provisioning.py::provision_for_request` — ensure one active `InferenceProfile` per model (`create_inference_profile` + persist) **before** `provision_key(...)`; `DuplicateKeyError`→409, other `AwsServiceError`→502; one-active-key enforced by the partial unique index + pre-check (commit-time `IntegrityError`→409). **AWS side-effects are compensated** on any failure (during provisioning or at commit) via `compensate_aws(...)` — created profiles deleted, provisioned key revoked — so AWS state never drifts from a rolled-back DB (see `ProvisionOutcome`). **Key management lives at `/api/keys`** (`GET` scoped list + `?status=&cost_centre_id=&developer_id=` filters / `GET {id}` / `POST {id}/revoke` / `POST {id}/regenerate` / `PATCH {id}/constraints`). `KeyOut` carries `inference_profiles[]` (for `modelOverrides` setup instructions) but **never** a token. **Revoke** = dev-owner / CCO-of-CC / admin; **regenerate** = dev-owner / admin only (the token is the developer's secret — CCO→403; returns `ProvisionedKeyOut` with the new token once via `aws.reset_key`); **constraints** = CCO-of-CC / admin only (dev-owner→403; an `allowed_models` change ensures profiles + `aws.update_model_policy`, compensating on failure). All guard `status ∈ {active,stopped}` (else 409) and follow the `_can_see` 404-vs-403 convention. Frontend nav is role-gated `AppLayout` (Home / Cost centres / Key requests / Keys); `KeysPage` is role-adaptive — developers get a "My keys" dashboard (revoke, regenerate→`TokenReveal`, per-key setup instructions), CCOs/admins get a management table (status/CC filters + inline constraints editor). The whole UI uses the **"Bedrock Control Room"** dark design system (see Conventions). **Next: Phase 7** (cost tracking & budget enforcement): add `usage_snapshots`/`pricing_cache` (migration), the background polling loop that populates `keys.lifetime_spend` and drives `key.stopped`/`key.restarted`, and `/api/keys/{id}/usage` + CC usage endpoints — at which point the dashboard's "$0.00 … Phase 7" spend placeholder becomes live. The `/docs` and `/research` folders remain the canonical specification; build against them following `docs/implementation-plan.md` and record decisions/retros in `docs/implementation-log.md`.

### Local Dev — Build & Run

```bash
docker compose up           # from repo root: db :5432, backend :8000, frontend :5173
# frontend → http://localhost:5173 ; backend health → http://localhost:8000/api/health
```

Both services bind-mount source with live reload (uvicorn `--reload`, vite dev). The backend compose `command` runs `alembic upgrade head && python -m app.seed` before uvicorn (idempotent seed). Backend-only, outside Docker: `cd backend && uv sync && uv run uvicorn app.main:app --reload` (needs a reachable Postgres or health reports `database:"error"`). Backend tests: `cd backend && uv run pytest` (uses a separate `claudeaws_test` DB it creates; needs Postgres on `localhost:5432`). Frontend: `npm run build`, `npm run test` (Vitest).

**Scaffolding decisions** (rationale in `docs/implementation-log.md`): backend uses **uv** (not Poetry); Python pinned to **3.12** (`requires-python >=3.12,<3.13`); DB driver **psycopg v3** (`postgresql+psycopg://`); `docker-compose.yml` lives at repo root, Dockerfiles in `/docker`. **Gotchas:** (1) list/dict `Settings` fields supplied via env must use `Annotated[list[str], NoDecode]` + a splitting validator — pydantic-settings JSON-decodes them at the source before validators run (crashed `CORS_ORIGINS` on first boot). (2) After changing backend deps, recreate with `docker compose up -d --build --force-recreate --renew-anon-volumes backend` — the anonymous `/app/.venv` volume otherwise shadows the rebuilt venv (`ModuleNotFoundError`). (3) Generate Alembic migrations against an **empty** schema — `create_all` against the dev DB makes autogenerate diff to nothing; keep `create_all` to the test DB. (4) Same anonymous-volume trap on the **frontend**: the `/app/node_modules` volume shadows newly-added npm deps, so the dev server throws `Failed to resolve import "<pkg>"` (e.g. `react-router-dom`) even though `npm run build` passes on the host. After changing frontend deps, recreate with `docker compose up -d --build --force-recreate --renew-anon-volumes frontend`. (5) When a phase adds **new** frontend page/route files (not just edits to existing ones), the running Vite dev server may keep serving a stale module graph (new route resolves to the catch-all → redirects Home; new nav links missing). `docker compose restart frontend` before browser-verifying. (6) In git-bash, leading-slash CLI args get MSYS path-mangled (`/keys` → a Windows path); prefix Node/CLI invocations that take such args with `MSYS_NO_PATHCONV=1` (e.g. screenshot capture).

** KEEP ALL DOCUMENTATION CONSISTENT, MINIMISE DUPLICATION, NOT VERBOSE **

## What This Is

A self-service web app for provisioning and governing Claude Code access via AWS Bedrock within an organisation. The platform **provisions and governs credentials but does not sit in the inference path** — developers get a bearer token (`AWS_BEARER_TOKEN_BEDROCK`) and call Bedrock directly from their terminal. This separation is fundamental: the app orchestrates AWS resources and polls usage, but never proxies model calls.

Three roles (a user can hold several at once): **Developer** (requests/uses keys), **Cost Centre Owner / CCO** (approves requests, sets per-key constraints, owns budgets), **Administrator** (global config, manages cost centres and users).

## Tech Stack (decided, not yet built)

- **Backend:** Python + FastAPI, `boto3`, Pydantic, SQLAlchemy + Alembic. Background scheduler (APScheduler or FastAPI tasks) for the usage-polling/budget-enforcement loop.
- **Frontend:** React + Vite + TypeScript, React Router, TanStack Query. Component library not yet chosen.
- **Database:** PostgreSQL (JSONB for policy docs / audit metadata / approval constraints).
- **Deployment:** Docker Compose locally (`backend` :8000, `frontend` :5173 proxying `/api`, `db` :5432); Docker on ECS + RDS/Aurora in production.

Planned monorepo layout (Phase 1): `/backend`, `/frontend`, `/docker`.

## Architecture — Non-Obvious Essentials

These are load-bearing decisions that span multiple docs. Read `docs/design-decisions.md` for full rationale before changing any of them.

- **Credential model = Bedrock API Keys (long-term).** Each key creates a backing **IAM user** named `claude-{developer}-{cc_code}`, tagged with developer + cost centre. This gives per-key attribution automatically via CloudTrail. Lifecycle uses `CreateServiceSpecificCredential` / `Update...(Status=Inactive)` / `Reset...` / `Delete...`.
- **Bearer tokens are NEVER stored.** No token column anywhere in the schema. The token is returned once in the provisioning/regeneration API response and displayed once in the UI. Lost token → developer regenerates (`ResetServiceSpecificCredential`), which invalidates the old one. Do not add token persistence or a "retrieve key" feature.
- **Model restrictions are enforced at the AWS/IAM layer, not in the app.** An inline IAM policy on the user scopes `bedrock:InvokeModel` to approved model ARNs, plus `bedrock:CallWithBearerToken` and inference-profile read actions. App-level checks alone are insufficient — a developer with the bearer token could bypass them.
- **Inference profiles: one per cost centre PER model.** A CC allowing Sonnet + Haiku has 2 profiles. CloudWatch metrics are keyed per inference profile → CC-level token counts. Developer setup uses Claude Code's `modelOverrides` to map each model to its CC-specific profile ARN.
- **Cost tracking is app-calculated** (tokens × cached pricing), NOT AWS Cost Explorer (24–48h lag is incompatible with rolling budgets). CloudWatch metrics drive near-real-time CC counts; invocation logs give per-key drill-down.
- **Budget enforcement = background polling loop every 2 minutes.** Each cycle: pull CloudWatch token counts → compute cost → update `usage_snapshots` → check per-key rolling/lifetime limits and CC budget cap → disable keys (set status `stopped`) when exceeded → re-enable when rolling-window spend drops or budget increases. Enforcement is a **hard stop** (key deactivated), never throttling. Accepted overshoot: up to ~2 min per developer.
- **Rolling budgets are sliding windows of configurable days**, not calendar periods. Rolling spend = `SUM(usage_snapshots.cost) WHERE key_id=? AND period_start >= NOW() - INTERVAL '? days'`.
- **AWS integration is abstracted behind an interface with a mock implementation.** Day-to-day dev runs `AWS_MODE=mock` (in-memory, no AWS cost, offline); integration tests and the PoC demo run `AWS_MODE=real` against a dedicated AWS account. App code must never call `boto3` directly — always go through the AWS service layer.
- **Region:** `ap-southeast-2` (Australia). Single region, single dedicated AWS account.

## Data Model

`docs/data-model.md` is the canonical schema reference (PostgreSQL DDL-level detail) and is the source of truth for SQLAlchemy models and Alembic migrations. Core tables: `users`, `cost_centres`, `cost_centre_owners`, `key_requests`, `keys`, `inference_profiles`, `usage_snapshots`, `pricing_cache`, `alert_configs`, `alert_history`, `audit_log`, `global_settings`.

Key invariants enforced at the DB/app boundary:
- One active key per developer per cost centre — partial unique index on `keys(developer_id, cost_centre_id) WHERE status IN ('active','stopped')`.
- CCO auto-approval: if the requesting developer is a CCO of the target CC, the request is created already `approved` with `reviewed_by = developer_id`.
- Approval constraints live in `key_requests.approved_constraints` (JSONB) and are copied to typed columns on `keys` at provisioning.
- `audit_log` is append-only (no updates/deletes); admin-only access.

## PoC Auth

Hard-coded users for the PoC (`admin/admin`, `dev1/dev1`, `ccowner1/ccowner1`, etc.) with bcrypt hashes seeded into `users`, JWT issued on login. Corporate SSO (OIDC/SAML) is explicitly **deferred to production** — don't build it for the PoC.

## Deferred to Production (do NOT build in PoC)

Email/Slack notifications (in-app alerts only for PoC), CSV export, Bedrock Guardrails / content filtering, SSO auto-offboarding, drift reconciliation, usage-spike detection. The `alert_configs` schema includes Slack/email channel fields, but the PoC only surfaces alerts in the UI.

## Conventions

- **British/Australian spelling** throughout docs and domain language: "cost centre" (not "cost center"), "organisation", "visualisation". Match this in code identifiers and UI copy where it touches domain terms — though note AWS API names and the `AWS_BEARER_TOKEN_BEDROCK` env var use their literal forms.
- **Frontend design system — "Bedrock Control Room"** (applied across the whole app via the `frontend-design` skill). Committed **dark-only** technical/console aesthetic; do **not** reintroduce `prefers-color-scheme` light variants. **Design tokens live in `frontend/src/index.css`** as CSS custom properties (`--bg`/`--bg-elev`/`--line`/`--text`/`--accent` (warm amber) + semantic `--ok`/`--warn`/`--danger`, radii, shadows); **component styles in `frontend/src/App.css`** keyed to the existing class names. Fonts: **IBM Plex Mono** (brand, headings, labels, code, numbers, badges, buttons) + **IBM Plex Sans** (body), loaded in `index.html`. **New UI must reuse these tokens and the existing class vocabulary** (`.panel`/`.table`/`.badge--*`/`.btn`/`.form--inline`/`.token-reveal`/`.status--error`, etc.) rather than hand-rolling colours — styling is centralised in those two CSS files (components carry classes, not inline styles). Respect `prefers-reduced-motion` (already handled globally). The live UI is verifiable in a browser at `:5173` (see the frontend node_modules gotcha (4) if imports fail to resolve there).

## Doc Map

- `docs/requirements.md` — functional + non-functional requirements, resolved decisions table.
- `docs/design.md` — C4 context/container diagrams, component layers, key sequence flows.
- `docs/data-model.md` — canonical DB schema.
- `docs/design-decisions.md` — the 11 numbered architectural decisions with rationale (read before changing architecture).
- `docs/implementation-plan.md` — the 11-phase build sequence with per-phase checklists.
- `docs/implementation-log.md` — live build progress, decisions taken during implementation, and per-phase retros.
- `docs/tech-spike.md` — hands-on AWS validation items to confirm before/during the build.
- `docs/test-strategy.md` — automation test strategy (unit, integration, UI, E2E) aligned to the mock-first phased build.
- `research/01`–`research/09` — supporting research on Bedrock config, IAM, model access, cost tracking, auth/SSO, guardrails, developer setup, and Bedrock API keys.
