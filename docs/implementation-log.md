# Implementation Log

High-level progress tracker for the build. Complements [implementation-plan.md](implementation-plan.md) (the spec) by recording what was actually done, decisions taken during the build, and per-phase retros. Keep entries terse.

## Status at a glance

| Phase | Title | Status |
|-------|-------|--------|
| 1 | Project Scaffolding & Local Dev Environment | ✅ Done |
| 2 | Database Models & Hard-Coded Auth | ✅ Done |
| 3 | Cost Centre Management (Admin) | ✅ Done |
| 4 | AWS Integration Layer (Mock Only) | ✅ Done |
| 5 | Key Request & Approval Flow | ✅ Done |
| 6 | Key Management & Developer Dashboard | ⬜ Not started |
| 7 | Cost Tracking & Budget Enforcement | ⬜ Not started |
| 8 | Dashboards & Visualisations | ⬜ Not started |
| 9 | Budget Alerts & Global Policies | ⬜ Not started |
| 10 | Key Expiry, Lifecycle Automation & Audit | ⬜ Not started |
| 11 | Real AWS Implementation, Integration & Polish | ⬜ Not started |

---

## Phase 1 — Project Scaffolding & Local Dev Environment

**Goal:** Skeleton monorepo that runs locally with `docker compose up` — frontend loads, hits backend health endpoint, backend connects to db.

### Decisions taken during build

- **Backend package manager: `uv`** (plan allowed Poetry/uv). Faster, single lockfile, manages its own Python.
- **Python pinned to 3.12** in containers and via `.python-version`. Local default is 3.14 which is too new for reliable pydantic/SQLAlchemy wheels.
- **DB driver: psycopg v3** → SQLAlchemy URL `postgresql+psycopg://`.
- **`docker-compose.yml` at repo root** so the documented `docker compose up` verify step works unchanged; Dockerfiles live in `/docker` (`backend.Dockerfile`, `frontend.Dockerfile`) per the planned `/docker` folder.
- **Health endpoint:** `GET /api/health` → `{"status":"ok","database":"ok"}`; actually executes `SELECT 1` against the DB so the verify step proves backend↔db connectivity.
- **Alembic scaffolded but no migration yet** — Phase 1 is "initial empty schema"; tables arrive in Phase 2.
- **DB credentials (local only):** db `claudeaws` / user `claudeaws` / password `claudeaws`.

### Progress

- [x] Monorepo structure (`/backend`, `/frontend`, `/docker`)
- [x] Backend: FastAPI + `/api/health` (pings DB) + pydantic-settings + uv config
- [x] Frontend: React + Vite + TS + env-driven `/api` proxy + health card
- [x] PostgreSQL 16 service (empty schema, no migrations yet)
- [x] Docker Compose wiring all three (root `docker-compose.yml`)
- [x] SQLAlchemy 2.0 + Alembic scaffold (engine/session/get_db, `env.py` reads settings)
- [x] Verified: `docker compose up` → db healthy → backend `database:"ok"` → frontend serves app + proxy reaches backend

### What was built

```
docker-compose.yml          root; backend:8000, frontend:5173, db:5432
.env.example , .gitignore
docker/backend.Dockerfile   python:3.12-slim + uv sync --frozen
docker/frontend.Dockerfile  node:22-slim + npm install + vite dev --host
backend/  app/{main,config}.py, app/api/health.py, app/db/{base,session}.py,
          alembic/ (env.py wired to settings, no versions yet), tests/test_health.py
frontend/ src/{main,App}.tsx (health card), vite.config.ts (env-driven proxy)
```

Both services bind-mount their source with an anonymous volume over `.venv` / `node_modules`, and run with live reload (uvicorn `--reload`, vite dev) for fast iteration in later phases.

### Retro

**What went well**
- Parallel subagents (backend + frontend) against a written shared contract (ports, `/api` prefix, `DATABASE_URL` form, health JSON shape) integrated with zero interface mismatches.
- Health endpoint actually executes `SELECT 1`, so the verify step genuinely proves backend↔db connectivity rather than just "process is up".
- Docker build cached cleanly; full stack came up on first `docker compose up`.

**What bit us (and the lesson)**
- **pydantic-settings JSON-decodes `list` fields from env vars *before* `field_validator(mode="before")` runs.** `CORS_ORIGINS=http://localhost:5173` (valid in compose, not valid JSON) crashed backend startup. Local `pytest` passed because no env var was set — the default list was used. Fix: annotate the field `Annotated[list[str], NoDecode]`. **Lesson: any list/dict setting that may be supplied as a plain string via env needs `NoDecode` + a splitting validator, and tests should exercise the env-var path, not just defaults.**
- The Chrome extension wasn't connected, so the rendered UI couldn't be visually verified in a browser. The data path (proxy → backend → db) is proven via curl and the React fetch logic was read, but the literal pixel render is unconfirmed. **Lesson: don't claim UI render success without a browser; state it as unverified.**

**Carry-forward for Phase 2**
- Add `alembic upgrade head` to the backend container start (compose `command` or entrypoint) once the first migration exists.
- Add a test that loads `Settings` with env vars set (regression guard for the `NoDecode` issue).
- Backend `requires-python = ">=3.12,<3.13"`; keep new deps 3.12-compatible.

---

## Phase 2 — Database Models & Hard-Coded Auth

**Goal:** Core domain tables + PoC auth so every later phase has a user/role context. Users log in, JWT protects API routes, role context available everywhere.

### Plan

Scope = exactly the Phase 2 model set from the plan: `users`, `cost_centres`, `cost_centre_owners`, `key_requests`, `keys`, `audit_log`, `global_settings`. Deferred-model tables (`inference_profiles` → P5, `usage_snapshots`/`pricing_cache` → P7, `alert_*` → P9) are **not** created yet — they arrive with the phase that uses them.

Built by two parallel agents against a shared **auth API contract** (mirrors the Phase 1 approach), then integrated + validated by the orchestrator.

**Auth API contract (frozen for both agents):**
- `POST /api/auth/login` — body `{username, password}` → `200 {access_token, token_type:"bearer", user:{id, username, display_name, email, roles[]}}`; bad creds → `401 {detail}`.
- `GET /api/auth/me` — `Authorization: Bearer <jwt>` → `200 {id, username, display_name, email, roles[], is_active}`; missing/invalid/expired → `401`.
- JWT: HS256, `sub`=user id, `exp`; secret/expiry from settings.

**Backend stream:**
- SQLAlchemy 2.0 models (`Mapped`/`mapped_column`) for the 7 tables, UUID PKs (`gen_random_uuid()`), `TimestampMixin`, Postgres `ARRAY`/`JSONB`/`INET`. Partial unique index `uq_keys_active_dev_cc` on `keys(developer_id, cost_centre_id) WHERE status IN ('active','stopped')`.
- Alembic initial migration (autogenerate via the compose db, then hand-verify the partial index).
- Idempotent seed (`python -m app.seed`): users `admin/admin`, `dev1/dev1`, `dev2/dev2`, `ccowner1/ccowner1` (bcrypt) + `global_settings` defaults (region, allowed models, default expiry/limits).
- Auth: bcrypt hashing, PyJWT issue/verify, `/api/auth/*` router, `get_current_user` + `require_roles(...)` dependencies.
- Tests: L1 (jwt/password/role logic), L3 (login, /me, 401 paths) against a real Postgres test db (`conftest` create_all + transactional rollback).
- New deps: `pyjwt`, `bcrypt`. Settings: `jwt_secret`, `jwt_algorithm`, `jwt_expiry_minutes`.

**Frontend stream:**
- Add `react-router-dom`, `@tanstack/react-query`.
- `AuthProvider` (token in localStorage, user state, login/logout, restore via `/api/auth/me`), `api` fetch helper that attaches the bearer token and logs out on 401.
- `/login` page (public), `ProtectedRoute` wrapper, minimal protected `/` home showing current user + roles + logout (replaces the health card as the landing).
- Tests: Vitest + RTL + MSW — login submits & stores token; ProtectedRoute redirects when unauthenticated.

**Integration/validation (orchestrator):**
- Generate + apply the migration against the compose db; wire `alembic upgrade head && python -m app.seed` into the backend container start.
- Run backend pytest + frontend `npm run build`/vitest; bring up the full stack; verify login via curl (and browser if the Chrome extension is connected).

### Progress

- [x] Backend models (7 tables) + Alembic initial migration + idempotent seed
- [x] Backend auth (login, /me, `get_current_user`, `require_roles`) + tests
- [x] Frontend login + auth context + protected routes + tests
- [x] Container start runs migrate + seed
- [x] Full-stack validation (login end-to-end)

### Decisions taken during build

- **JWT lib = PyJWT; password hashing = `bcrypt` directly** (not passlib — avoids the passlib/bcrypt 4.x maintenance friction). HS256, `sub`=user id, `exp` from `jwt_expiry_minutes` (default 480). Settings: `jwt_secret`/`jwt_algorithm`/`jwt_expiry_minutes`. Default dev secret lengthened to ≥32 bytes to silence PyJWT's `InsecureKeyLengthWarning`; documented in `.env.example` (use a real random secret anywhere shared).
- **Only the 7 Phase-2 tables** were created. Deferred-model tables are intentionally absent until their phase.
- **Unique columns** (`username`, `email`, `code`, `iam_username`, `credential_id`, `key_request_id`) were implemented as `UniqueConstraint`s rather than the named unique *indexes* in data-model.md. Functionally identical (a unique constraint is backed by a unique index); names differ. Not worth reworking.
- **`get_current_user` + `require_roles(*roles)`** live in `app/core/deps.py` — the reusable RBAC primitives every later phase imports.
- **Migration is migration-managed, not `create_all`.** Dev `claudeaws` db is now owned by Alembic (`alembic_version` = `57f0fe8dd206`). Tests use a separate `claudeaws_test` db (conftest: `create_all` + per-test transactional rollback).
- **Container start** (compose `command`): `alembic upgrade head && python -m app.seed && uvicorn …` (PATH resolves the venv binaries).
- **Email stored as plain `str`** in schemas (not `EmailStr`) to avoid pulling in `email-validator`.

### What was built

```
backend/app/models/   _mixins.py (TimestampMixin) + user, cost_centre, cost_centre_owner,
                      key_request, key, audit_log, global_setting; __init__ imports all 7
backend/app/core/     security.py (bcrypt + PyJWT), deps.py (get_current_user, require_roles)
backend/app/api/auth.py + app/schemas/auth.py   /api/auth/login, /api/auth/me
backend/app/seed.py   idempotent: 4 users (bcrypt) + 5 global_settings
backend/alembic/versions/57f0fe8dd206_*.py   initial schema (7 tables, partial unique index)
backend/tests/        conftest (claudeaws_test + rollback), test_security, test_rbac, test_auth
frontend/src/         lib/api.ts, auth/{AuthContext,ProtectedRoute}, pages/{LoginPage,HomePage},
                      mocks/ + test/ (MSW+RTL); App.tsx routes, main.tsx providers
```

Seed personas: `admin/admin` (admin), `dev1/dev1` & `dev2/dev2` (developer), `ccowner1/ccowner1` (cco+developer).

### Validation

- Backend: **17 passed** (9 L1 unit, 6 L3 auth integration, 2 health), no warnings.
- Frontend: `npm run build` passes (tsc strict); **5 Vitest tests** pass; dev server serves HTTP 200.
- Live stack (`docker compose up`): `/api/health` → `database:"ok"`; login `admin`/`ccowner1` returns token + correct roles; `/api/auth/me` validates; bad creds → 401; missing token → 401. End-to-end via curl.

### Retro

**What went well**
- Two parallel agents (backend / frontend) against a frozen auth contract integrated with zero interface drift — same pattern that worked in Phase 1. Splitting the DB-dependent migration generation + full-stack validation out to the orchestrator kept the agents deterministic and offline.
- Autogenerate emitted the tricky bits correctly once pointed at a clean DB: `gen_random_uuid()` defaults, `roles` array default, and the partial unique index `uq_keys_active_dev_cc` with `postgresql_where` (up **and** down).

**What bit us (and the lesson)**
- **Stale anonymous `.venv` volume.** After adding `pyjwt`/`bcrypt` and rebuilding the image, the backend crashed `ModuleNotFoundError: bcrypt`. Compose preserves the Phase-1 anonymous `/app/.venv` volume across `up`, shadowing the freshly built venv. **Lesson: whenever backend deps change, recreate with `docker compose up -d --build --force-recreate --renew-anon-volumes backend` (or `down -v`), not a plain `up --build`.**
- **Autogenerate against a dirty DB = empty migration.** The agent had run `create_all` (to exercise the seed) against the dev `claudeaws` db, so the first autogenerate diffed to nothing. **Lesson: generate the initial migration against a genuinely empty schema; keep `create_all` confined to the test DB.** Now resolved — `claudeaws` is Alembic-managed.
- **Browser render still unverified.** Chrome extension not connected (as in Phase 1). Login UI is covered by build + RTL/MSW component tests and the dev server returns 200, but pixels are unconfirmed.

**Carry-forward for Phase 3**
- Backend dep change ⇒ `--renew-anon-volumes` (see above).
- Reuse `require_roles(...)` for the admin-only cost-centre endpoints; reuse the seed personas as Phase 3+ test fixtures.
- `audit_log` table exists but nothing writes to it yet — Phase 3 (cost-centre create/archive/owner changes) is the first writer; establish a small audit helper there.
- Add an Alembic-migration test (migrate up from empty matches models) per test-strategy L3 — not yet present.
- New frontend pages should hang off the existing `AuthProvider`/`ProtectedRoute`/`api.ts`; gate admin UI on `hasRole('admin')`.

---

## Phase 3 — Cost Centre Management (Admin)

**Goal:** Admins create/manage cost centres (the org unit everything hangs off) and assign CCOs. Developers see a read-only list of active cost centres (for the future key-request flow). Establishes the first `audit_log` writer.

### Plan

**No migration needed** — `cost_centres`, `cost_centre_owners`, `audit_log` all exist from Phase 2. Pure API + frontend + the first audit helper. Built by two parallel agents against a frozen API contract (same pattern as P1/P2), then orchestrator integrates (register router) + validates (pytest, build, live stack via curl).

**Cost-centre API contract (frozen for both agents):** all routes require auth (bearer JWT).

`CostCentre` response shape:
```json
{ "id": uuid, "code": "CC-1234", "name": str, "description": str|null,
  "status": "active"|"archived", "budget_cap": number|null, "created_by": uuid,
  "created_at": iso, "updated_at": iso,
  "owners": [ { "user_id": uuid, "username": str, "display_name": str, "assigned_at": iso } ] }
```

- `POST /api/cost-centres` — **admin**. Body `{code, name, description?, budget_cap?}` → `201 CostCentre`. Dup code → `409`.
- `GET /api/cost-centres` — auth. admin → all; non-admin → only `status='active'`. → `200 [CostCentre]`.
- `GET /api/cost-centres/{id}` — auth. non-admin requesting archived → `404`. → `200 CostCentre`.
- `PATCH /api/cost-centres/{id}` — **admin**. Body `{name?, description?, budget_cap?}` (code immutable) → `200 CostCentre`.
- `POST /api/cost-centres/{id}/archive` | `/unarchive` — **admin** → `200 CostCentre`. No-op if already in target state (no dup audit row).
- `POST /api/cost-centres/{id}/owners` — **admin**. Body `{user_id}` → `200 CostCentre`. Grants `cco` role if missing. Already-owner → `409`; unknown user → `404`.
- `DELETE /api/cost-centres/{id}/owners/{user_id}` — **admin** → `200 CostCentre`. Strips `cco` role if the user owns no remaining CCs.
- `GET /api/users` — **admin** (supporting endpoint for the owner picker). → `200 [{id, username, display_name, email, roles, is_active}]`.

**Audit:** small reusable helper `app/core/audit.py` `record_audit(db, *, actor_id, action, entity_type, entity_id, old_values=None, new_values=None, ip_address=None)`. Actions emitted: `cost_centre.created`, `cost_centre.updated` (full old/new diff — covers budget too; doc enum is non-exhaustive), `cost_centre.archived`, `cost_centre.unarchived`, `cco.assigned`, `cco.removed`.

**Deferred to their owning phases** (no writers exist yet): archive does **not** yet cascade-disable keys / auto-reject pending requests (Phase 5/6 own those tables). Documented as a known gap.

**Frontend:** introduce a minimal `AppLayout` (role-gated nav: Home, Cost Centres) since the app outgrows the single centred card. `CostCentresPage` — table of cost centres; admins get create/edit/archive controls + an owners panel (assign via user picker, remove); developers get a read-only active-only list. TanStack Query hooks against the contract; MSW handlers + Vitest coverage. Hang off existing `AuthProvider`/`ProtectedRoute`/`api.ts`.

### Progress

- [x] Backend: schemas + audit helper + cost-centre router + `GET /api/users` + register in `main.py`
- [x] Backend tests (RBAC, CRUD, archive/unarchive, owners, audit writes, dev scoping)
- [x] Frontend: layout/nav + cost-centre page + hooks + MSW + Vitest
- [x] Integration: pytest + build/vitest + live-stack curl verification

### Decisions taken during build

- **First `audit_log` writer = `app/core/audit.py::record_audit(...)`** — keyword-only, `db.add`s the row but does **not** commit (the request handler owns the transaction). Includes a `_jsonable` coercion (UUID→str, Decimal→float, datetime→isoformat) so JSONB `old/new_values` never choke on ORM types. Every later phase (keys, requests, settings) reuses this.
- **`audit_log.ip_address` is Postgres `INET`** → a `_client_ip` guard parses `request.client.host` with `ipaddress.ip_address(...)` and stores `None` for non-IP hosts (e.g. the TestClient's `"testclient"`), rather than crashing on insert.
- **PATCH emits `cost_centre.updated`** with an old/new diff of only the changed fields (covers budget changes too); the doc's `cost_centre.budget_updated` action is subsumed — the audit enum is explicitly non-exhaustive. No audit row written when nothing changed.
- **archive/unarchive are no-ops when already in the target state** — no status write, no duplicate audit row.
- **CCO role lifecycle is automatic:** assigning an owner grants the `cco` role (list **reassignment**, since SQLAlchemy doesn't track in-place `ARRAY` mutation); removing the owner strips `cco` **only if** the user owns no other cost centre. Other roles untouched.
- **Supporting `GET /api/users`** (admin-only, `app/api/users.py`) added beyond the plan's endpoint list — the owner-assignment picker needs a user list to choose from.
- **Frontend gained an `AppLayout`** (role-gated top nav: Home / Cost centres + user + logout) since the app outgrew the single centred card; authed pages now use a wider `.page--wide` container, login keeps the card.
- **Deferred (no writers exist yet):** archiving a CC does **not** yet cascade-disable its keys or auto-reject pending requests — those tables/writers arrive in Phase 5/6. Known gap, revisit there.

### What was built

```
backend/app/core/audit.py                first audit_log writer (record_audit + _jsonable)
backend/app/schemas/cost_centre.py        CostCentre, OwnerSummary, Create/Update, OwnerAssign
backend/app/schemas/user.py               UserListItem
backend/app/api/cost_centres.py           8 endpoints (CRUD + archive/unarchive + owners)
backend/app/api/users.py                  GET /api/users (admin)
backend/app/main.py                        registers cost_centres + users routers
backend/tests/test_cost_centres.py         13 cases (RBAC, CRUD, archive, owners, audit, scoping)
frontend/src/components/AppLayout.tsx      role-gated nav + wide layout
frontend/src/features/costCentres/{types,api}.ts   typed client + TanStack Query hooks
frontend/src/pages/CostCentresPage.tsx     table + admin create/edit/archive + owners panel
frontend/src/pages/CostCentresPage.test.tsx 6 Vitest cases
frontend/src/{App.tsx,pages/HomePage.tsx,App.css,mocks/handlers.ts,test/setup.ts}  wired in
```

### Validation

- Backend: **36 passed** (23 prior + 13 new), local Postgres on :5432.
- Frontend: `npm run build` (tsc strict + vite) passes; **11 Vitest tests** pass (5 prior + 6 new).
- Live stack (`docker compose up`, backend hot-reloaded the new routes): full curl sweep green — admin create + `409` dup; `dev1` create `403`, `dev1 GET /api/users` `403`, unauth list `401`; assign `dev2` owner → `dev2` gains `cco`; re-assign `409`; archive → invisible to `dev1` (list + `404` by id); unarchive + remove owner → `cco` stripped from `dev2`.

### Retro

**What went well**
- Same two-parallel-agents-against-a-frozen-contract pattern (P1/P2) again integrated with zero interface drift — backend 36/36, frontend 11/11 on first orchestrator run. No migration this phase (tables already existed) made integration a pure router-registration + validation step.
- `record_audit` landed as a clean reusable primitive on the first writer, exactly as the P2 carry-forward asked.

**What bit us (and the lesson)**
- **`INET` rejects non-IP hosts.** Storing `request.client.host` directly would crash under the TestClient (host = `"testclient"`). **Lesson: validate before writing to typed Postgres columns (`INET`, etc.); coerce invalid values to NULL.**
- **Browser render still unverified** — Chrome extension not connected (as P1/P2). UI covered by build + RTL/MSW only; pixels unconfirmed.
- The live curl sweep mutated the dev DB (left one stray active `CC-E2E-*` cost centre; `dev2` correctly back to `['developer']`). Harmless local test residue; re-seed is idempotent and won't remove it.

**Carry-forward for Phase 4**
- Reuse `record_audit` for every state change; pass `_client_ip(request)`.
- When Phase 5/6 add key/request writers, wire the deferred archive cascade (disable keys, auto-reject pending requests on archive) and revisit `cost_centres` status transitions.
- AWS layer (Phase 4) is mock-only and must sit behind the interface — no `boto3` in app code. Run the tech-spike "validate before you mock" items first.
- Still missing the Alembic-migration test (migrate-up-from-empty matches models) flagged in P1/P2 — fold into a future phase.

---

## Phase 4 — AWS Integration Layer (Mock Only)

**Goal:** An abstracted AWS service layer (`app/services/aws/`) that every later phase calls instead of `boto3`, with a realistic in-memory mock. Backend-only — no frontend, no migration (the `inference_profiles`/`usage_snapshots` *tables* land with their owning phases; the mock keeps state in-memory). Real boto3 deferred to Phase 11.

### "Validate before you mock" — status (honest gap)

The plan asks to run tech-spike #1–#3 against real AWS *before* building the mock, so the mock's usage-data **shape and timing** mirror reality. **These were not run** — this environment is offline with no AWS account (the whole point of mock-first). The mock instead encodes the **documented** shape: the design-decisions "Resolved Questions" table + research/04 (CloudWatch `InputTokenCount`/`OutputTokenCount` per inference profile; invocation logs per IAM-user with input/output token counts + modelId). The usage-shape assumptions are therefore **flagged risks**, isolated in one module (`usage.py`) and one tunable (`base_tokens_per_minute`) so Phase 11 can reconcile against the spike with minimal blast radius. `tech-spike.md` status stays "Not yet tested".

### Plan — built by two parallel agents against a frozen contract (P1–P3 pattern)

**Module layout** `backend/app/services/aws/`:
- `base.py` — `AwsService` ABC, dataclasses (`ProvisionedKey`, `TokenUsage`, `KeyUsage`, `InferenceProfileRef`), exceptions (`AwsServiceError` + `KeyNotFoundError`/`ProfileNotFoundError`/`DuplicateProfileError`), `UsageSimulatorProtocol`, and `build_model_policy(...)` (allowed_models → IAM policy doc, per Decision #3/#13 exact-ARN).
- `mock.py` — `MockAwsService(AwsService)`: in-memory IAM-user/credential/profile state machine; composes a `UsageSimulator`; clock-injectable.
- `usage.py` — `UsageSimulator`: deterministic, clock-driven, monotonic token accrual with pause/resume on disable/enable (transition-history integration so windowed `[start,end]` queries work). The riskiest assumption, isolated here.
- `real.py` — `RealAwsService(AwsService)` stub; every method raises `NotImplementedError("Real AWS arrives in Phase 11")`.
- `__init__.py` — `get_aws_service()` factory (lru_cache singleton so the in-memory mock persists across requests), wired to `settings.aws_mode` (`mock`→mock, `real`→stub, else ValueError). Exports the public API.

**Frozen interface** (keyword-only, mirrors `record_audit` style). Signatures refined from the plan's indicative list and documented below:
- `provision_key(*, iam_username, cost_centre_code, allowed_models, expiry_days) -> ProvisionedKey` — *added `cost_centre_code`* so the mock can resolve each allowed model to its CC+model inference profile (key↔profile↔CC graph drives realistic usage); *renamed `model_policy`→`allowed_models`* (the layer builds the IAM policy internally, symmetric with `update_model_policy`).
- `revoke_key(*, iam_username, credential_id)`, `disable_key(*, credential_id)`, `enable_key(*, credential_id)`, `reset_key(*, credential_id) -> str` (new bearer token), `update_model_policy(*, iam_username, allowed_models)`.
- `create_inference_profile(*, cost_centre_code, model_id) -> InferenceProfileRef` (arn+name; Phase 5 persists both), `delete_inference_profile(*, profile_arn)`.
- `get_usage_metrics(*, profile_arn, start, end) -> TokenUsage` (CloudWatch CC-level, `key_id=NULL` path), `parse_invocation_logs(*, since) -> list[KeyUsage]` (per-IAM-user path).

**Usage realism (Decision #2/#12):** keys accrue tokens while active at a per-key deterministic rate (hash of credential_id → stable ±variance) so different keys burn differently and *actually approach/cross limits*; disabled keys pause. Token split input/output/cache-read/cache-write by fixed plausible ratios (Claude Code = heavy cache reads). **Cost is NOT computed here** — the layer returns token counts only; cost = tokens × pricing arrives in Phase 7.

- **Agent A (aws-core):** `base.py`, `mock.py`, `real.py`, `__init__.py` (factory).
- **Agent B (aws-usage+tests):** `usage.py` (`UsageSimulator` impl of the frozen protocol) + `tests/test_aws_mock.py` (L2 suite: provision returns id+token once; disable/enable/reset/revoke transitions + error cases; policy built from exact model ARNs; profile create/dup/delete; usage accrues monotonically, pauses when disabled, windowed queries, per-key invocation logs; `AWS_MODE` factory routing incl. real-stub raises).
- **Orchestrator (me):** wire imports, run `pytest`, fix integration, independent review pass, retro + doc updates.

No dependency changes (clock injected, not `freezegun`) → no `--renew-anon-volumes` needed.

### Progress

- [x] Agent A (aws-core): `base.py` (ABC + dataclasses + exceptions + `build_model_policy`) + `mock.py` + `real.py` (stub) + `__init__.py` (factory)
- [x] Agent B (aws-usage): `usage.py` (`UsageSimulator`) + `tests/test_aws_mock.py`
- [x] Integrate + `pytest` green (**68 passed**; 36 prior + 32 AWS-mock L2)
- [x] Orchestrator review pass + docs/retro

### Decisions taken during build

- **Module layout `app/services/aws/`**: `base.py` (interface + value objects + exceptions + `UsageSimulatorProtocol` + `build_model_policy`), `mock.py` (`MockAwsService`), `usage.py` (`UsageSimulator`), `real.py` (`RealAwsService` stub), `__init__.py` (`get_aws_service` factory + public exports). App code imports `get_aws_service`; **no `boto3` anywhere** (smoke-checked: `boto3` not in `sys.modules` after import).
- **Factory is an `@lru_cache` singleton** so the in-memory mock's state survives across requests in the running app; usable directly as a FastAPI `Depends`. Tests construct `MockAwsService(clock=...)` directly for isolation.
- **Interface signature refinements** (the plan's list was indicative): `provision_key(*, iam_username, cost_centre_code, allowed_models, expiry_days)` — added `cost_centre_code` so the mock resolves each model to its CC+model inference profile (the key↔profile↔CC graph that drives realistic usage); `model_policy`→`allowed_models` (the layer builds the IAM policy internally, symmetric with `update_model_policy`). Usage methods take an explicit `start`/`end` window; `create_inference_profile → InferenceProfileRef(arn, name)` (Phase 5 persists both). All methods keyword-only (matches `record_audit` house style).
- **IAM policy built behind the interface** by `build_model_policy(allowed_models, ...)` — exact foundation-model ARNs, no wildcards (Decision #3/#13), mirroring design-decisions §3 (3 statements incl. `CallWithBearerToken` + inference-profile resolution). Mock stores the generated policy per key so behaviour is assertable now; real impl will `PutUserPolicy` the same doc in P11.
- **Usage realism** (`UsageSimulator`, the riskiest assumption — isolated in one file + one tunable `base_tokens_per_minute`): per-key burn rate is a deterministic hash of `credential_id` (factor ∈ [0.5, 1.5]) so keys differ but reproduce; accrual integrates an append-only `(timestamp, active)` transition timeline so **disabled keys pause and resume cleanly** and arbitrary `[start, end]` windows are answerable; token split is fixed plausible ratios (input 25 / output 15 / cache-read 55 / cache-write 5 — Claude Code is cache-read heavy). **Cost is NOT computed here** — the layer returns token counts only; cost = tokens × pricing arrives in Phase 7.
- **Multi-model attribution fix (orchestrator):** the first cut attributed a key's *full* burn to *each* allowed model, double-counting a multi-model key across the CloudWatch and invocation-log paths — a latent Phase-7 per-key-enforcement bug. Fixed to split a key's window burn **evenly across its models** (one profile per model), so per-key total = single window burn and each profile sees only its share. Locked with `test_multi_model_key_splits_burn_no_double_count`.
- **No new dependencies, no migration:** the clock is injected (not `freezegun`), and the mock is in-memory (the `inference_profiles`/`usage_snapshots` *tables* still arrive in P5/P7). So **no `--renew-anon-volumes` dance and no Alembic change** this phase.

### What was built

```
backend/app/services/__init__.py                  package marker
backend/app/services/aws/base.py                  AwsService ABC, ProvisionedKey/TokenUsage/KeyUsage/
                                                   InferenceProfileRef, AwsServiceError(+4 subclasses),
                                                   UsageSimulatorProtocol, build_model_policy (exact-ARN)
backend/app/services/aws/mock.py                   MockAwsService (in-memory key/profile state machine)
backend/app/services/aws/usage.py                  UsageSimulator (deterministic, clock-driven accrual)
backend/app/services/aws/real.py                   RealAwsService stub (NotImplementedError → Phase 11)
backend/app/services/aws/__init__.py               get_aws_service() factory (lru_cache) + exports
backend/tests/test_aws_mock.py                     32 L2 cases (pure/offline, controllable clock)
```

### Validation

- Backend: **68 passed** (36 prior + 32 new AWS-mock L2), local Postgres on :5432; AWS-mock suite alone runs in ~0.1 s (no DB/network).
- Smoke: `get_aws_service()` → `MockAwsService` singleton; `app.main` imports cleanly with the new package; **`boto3` not imported** anywhere.
- L2 coverage: provision returns id+token once + distinct per user; dup username/profile, not-found, mismatch error paths; reset returns a new token; disable/enable idempotent + pause accrual; revoke removes state; exact-ARN policy (no `claude-sonnet-*` wildcard, includes `CallWithBearerToken` + `application-inference-profile/*`); profile create/dup/delete/recreate; usage zero→grows, windowed additivity/monotonicity, pause-on-disable (~60 vs ~90 active min), per-key invocation logs, no-profile-for-model yields nothing, two keys on one profile sum to the metric, multi-model split; factory routing incl. real-stub `NotImplementedError` + unknown-mode `ValueError`.

### Retro

**What went well**
- The frozen-contract + parallel-agents pattern (P1–P3) adapted cleanly to a single-stream backend phase by splitting along a real seam: **aws-core** (interface + lifecycle state machine) vs **aws-usage** (the accrual engine + the whole L2 suite), joined by a frozen `UsageSimulatorProtocol`. Zero interface drift — aws-usage's tests went green against aws-core's files on first integration (68/68), and aws-usage even self-corrected a model-id constant against the real `base.py` mid-flight.
- Isolating the riskiest assumption (synthetic usage shape) into one file + one tunable means Phase 11's real-AWS reconciliation has a small, well-labelled blast radius.
- The accrual design (transition-timeline integration) made pause/resume and arbitrary windows fall out naturally and deterministically — exactly the clock-injected, no-wall-clock property the test-strategy demands.

**What bit us (and the lesson)**
- **"Validate before you mock" could not be honoured.** tech-spike #1–#3 need a live AWS account; this environment is offline by design. The mock encodes the *documented* shape, not measured reality, so the usage ratios/latency remain **unproven assumptions**. **Lesson: a mock-first build trades early UX feedback for the risk of baking in wrong AWS-behaviour assumptions — keep them isolated and labelled (done), and treat Phase 11 as a real reconciliation step, not a rubber-stamp.** `tech-spike.md` stays "Not yet tested".
- **First-cut usage double-counted multi-model keys.** Caught in orchestrator review, not by the agents' tests (which only exercised single-model keys). **Lesson: when two derived data paths must agree (CloudWatch CC-level vs per-key logs), add an explicit cross-path consistency test for the *multi-* case, not just the 1:1 golden path.**
- **Browser render N/A this phase** (backend-only) — the long-standing "pixels unverified" gap is untouched and still open for the frontend phases.

**Carry-forward for Phase 5**
- Inject the AWS layer via `Depends(get_aws_service)`; map `AwsServiceError` subclasses to HTTP (`DuplicateKeyError`→409, `KeyNotFoundError`→404, etc.) in the key-request/provisioning handlers.
- Phase 5 owns the **order**: on approval, for each approved model `create_inference_profile(cc_code, model)` (persist `InferenceProfileRef.profile_arn`/`profile_name` to the new `inference_profiles` table) **before** `provision_key(...)`, so the mock can resolve `model_profiles` and usage attributes correctly. Add the `InferenceProfile` model + migration in P5 (per plan).
- Reuse `record_audit` + `_client_ip` for every key/request state change; wire the **deferred archive cascade** (P3 gap: disable keys / auto-reject pending requests on CC archive) now that key writers exist.
- The bearer token from `ProvisionedKey.bearer_token` is returned **once** in the API response and never persisted (Decision #10) — no token column; do not add one.
- Usage-shape assumptions (ratios, rate, latency) live in `usage.py`/`base_tokens_per_minute` — tune so demo keys cross a $50/7-day rolling limit in a sensible wall-clock window once Phase 7 wires pricing; reconcile against the spike in Phase 11.
- Still missing the Alembic migrate-up-from-empty test (flagged P1/P2/P3) — fold into P5 when the next migration lands.

---

## Phase 5 — Key Request & Approval Flow

**Goal:** End-to-end key lifecycle — developer requests → CCO/admin approves with constraints (or auto-approval) → AWS layer provisions → bearer token shown **once**. First writers for `key_requests`, `keys`, `inference_profiles`. Closes the long-deferred CC-archive cascade.

### Key design decision (resolved from design.md §4.1 + plan)

**Provision on approval.** The approve / auto-approve response carries the bearer token **once** (`ProvisionedKey.bearer_token`); nothing is stored (Decision #10 — no token column). The clean single-actor demo path is **auto-approval**: a CCO requesting a key for a CC they own is created already `approved` and provisioned inline, so they see the token immediately. When a *different* CCO/admin approves a developer's request, the token is surfaced to the approver; the developer-obtains-own-token recovery path is Phase-6 regenerate (not built here). This matches design.md §4.1 (`P-->>Dev: Display token once`) and the data-model auto-approval rule.

### Plan — two parallel agents against a frozen contract (P1–P4 pattern)

**Frozen API contract** (under `/api/key-requests`, all auth'd). Mutating/listing responses use an envelope `{ "request": KeyRequest, "key": ProvisionedKey | null }`.

`KeyRequest` response: `{id, developer_id, developer_username, developer_display_name, cost_centre_id, cost_centre_code, cost_centre_name, status, justification, rejection_reason, reviewed_by, reviewed_at, approved_constraints, created_at, updated_at}`.

`ProvisionedKey` response (token shown once): `{id, cost_centre_id, cost_centre_code, iam_username, status, allowed_models, rolling_limit, rolling_period_days, lifetime_budget, expires_at, bearer_token, inference_profiles:[{model_id, profile_arn, profile_name}]}`.

- `POST /api/key-requests` — body `{cost_centre_id, justification?}`. 404 if CC missing/archived (non-admin); 409 if dev already has an active/stopped key **or** a pending request for that CC. If requester is a CCO of the target CC → auto-approve + provision with `global_settings` defaults → `201 {request(approved), key}`; else create pending → `201 {request(pending), key:null}`.
- `GET /api/key-requests?status=` — scoped: developer=own; CCO=requests for CCs they own (∪ own); admin=all. → `200 [KeyRequest]`.
- `GET /api/key-requests/{id}` — same visibility (else 404). → `200 KeyRequest`.
- `POST /api/key-requests/{id}/approve` — **admin or CCO-of-that-CC**. Body `{allowed_models?, rolling_limit?, rolling_period_days?, lifetime_budget?, expiry_days?}` (omitted → `global_settings` default; `allowed_models` must be ⊆ global allowed). 409 if not pending or dev already has an active key. Provisions → `200 {request, key}`.
- `POST /api/key-requests/{id}/reject` — admin/CCO-of-CC. Body `{rejection_reason}`. 409 if not pending → `200 {request, key:null}`.

**Provisioning order (per P4 carry-forward, in a `provisioning` service):** resolve constraints → for each allowed model ensure an active `InferenceProfile` for (CC, model) (query; if missing `aws.create_inference_profile` + persist) → `aws.provision_key(iam_username=claude-{username}-{cc_code}, cost_centre_code, allowed_models, expiry_days)` → persist `keys` row (copy constraints to typed cols, `expires_at=now+expiry_days`) → set `key_request` approved/reviewed_by/reviewed_at/approved_constraints → audit `key.approved` + `key.provisioned` → commit. Map `AwsServiceError` subclasses to HTTP (`DuplicateKeyError`→409). One-active-key enforced by the partial unique index + pre-check (IntegrityError→409).

**Archive cascade (closes P3/P4 gap):** on `POST /cost-centres/{id}/archive` → auto-reject pending `key_requests` for that CC (`key.rejected`, reason "Cost centre archived") + revoke active/stopped `keys` via `aws.revoke_key` (status `revoked`, `revoked_at`, audit `key.revoked`). Inject `Depends(get_aws_service)`.

**New model + migration:** `InferenceProfile` (`app/models/inference_profile.py`: id, cost_centre_id FK, model_id, profile_arn unique, profile_name, status, created_at — **no** `updated_at`/TimestampMixin per data-model). Partial unique index `uq_inference_profiles_cc_model` on `(cost_centre_id, model_id) WHERE status='active'`. Register in `models/__init__.py`. Hand-authored Alembic migration (`down_revision=57f0fe8dd206`). **Also adds the long-flagged migrate-up-from-empty test** (P1/P2/P3 carry-forward).

- **Agent A (backend):** model + migration + schemas + `provisioning.py` service + `api/key_requests.py` + archive-cascade in `cost_centres.py` + register in `main.py` + `tests/test_key_requests.py` + `tests/test_migrations.py`. Runs pytest.
- **Agent B (frontend):** `features/keyRequests/{types,api}.ts` + role-adaptive `KeyRequestsPage` (developer request form + own-requests status list + token reveal w/ copy + setup instructions; CCO/admin pending list + approve modal (constraints) / reject modal (reason)) + nav link + `App.tsx` route + MSW handlers + Vitest. Runs build + vitest.
- **Orchestrator (me):** verify migration applies on the live DB, register/run full pytest + build + vitest, live curl sweep, review pass, retro + docs.

### Progress

- [x] Agent A (backend): model + migration + schemas + provisioning + API + archive cascade + tests
- [x] Agent B (frontend): feature client + page + token reveal + nav/route + MSW + Vitest
- [x] Integrate: migration applied (live DB at `a1b2c3d4e5f6`), full pytest + build + vitest green
- [x] Orchestrator review pass + live curl sweep + docs/retro

### Decisions taken during build

- **Provision-on-approval; token returned once in the response** (matches design.md §4.1). `KeyRequestResult = {request, key}`; `key` (with `bearer_token`) is non-null only on the provisioning responses (auto-approve, approve). Lists/GET never carry the token (verified live — no `bearer_token` field leaks into `GET /key-requests`). No token column added.
- **Auto-approval = requester is a CCO of the target CC** (via `cost_centre_owners`), not merely holding the `cco` role. Created already `approved`, `reviewed_by = requester`, provisioned inline with `global_settings` defaults.
- **Constraint resolution** (`_resolve_constraints`): start from `global_settings` (`allowed_models`, `default_rolling_limit.{amount,period_days}`, `default_lifetime_budget`, `default_key_expiry_days`), apply approve-time overrides; reject (400) any `allowed_models` not ⊆ the global allowed set.
- **`InferenceProfile` model has only `created_at`** (no `TimestampMixin`/`updated_at`, per data-model). Partial unique index `uq_inference_profiles_cc_model` on `(cost_centre_id, model_id) WHERE status='active'`.
- **Migration is hand-authored** (`a1b2c3d4e5f6`, `down_revision=57f0fe8dd206`) — not autogenerated (avoids the P2 dirty-DB footgun). `sa.UUID()`/`sa.text('now()')` idioms; partial index via `postgresql_where`.
- **Provisioning order** lives in `app/services/provisioning.py::provision_for_request` — look-up-or-create one active `InferenceProfile` per model **then** `aws.provision_key`, persist the `Key`, audit `key.provisioned`; no commit (router owns the txn, flushes for generated ids). `iam_username = f"claude-{username}-{cc_code}".lower()`.
- **Archive cascade wired (closes the P3/P4 gap):** `archive_cost_centre` now injects the AWS layer; on active→archived it auto-rejects pending requests (`key.rejected`) and revokes active/stopped keys via `aws.revoke_key` (`key.revoked`, swallowing `KeyNotFoundError`). Approved *requests* stay `approved` (it's their *keys* that are revoked).
- **AWS error mapping:** `DuplicateKeyError`→409, other `AwsServiceError`→502. One-active-key enforced by pre-check + the partial unique index.
- **Frontend token survival:** the reviewer-side `TokenReveal` is lifted to page state so it survives the TanStack-Query list invalidation that removes the just-approved row. Approve modal's model checkboxes use a `DEFAULT_MODEL_OPTIONS` constant mirroring the seed `allowed_models` (a real settings endpoint arrives in Phase 9); leaving all unticked sends no `allowed_models` (backend applies defaults).
- **Long-flagged Alembic test added** (`tests/test_migrations.py`, P1/P2/P3 carry-forward): migrate-up-from-empty on a throwaway DB → assert all 8 tables → downgrade to base. Redirects `env.py` via `DATABASE_URL` + `get_settings.cache_clear()`. Marked `@pytest.mark.slow` (marker registered in `pyproject.toml`); `path_separator = os` added to `alembic.ini` to silence the alembic deprecation warning.

### What was built

```
backend/app/models/inference_profile.py            InferenceProfile (created_at only; partial unique index)
backend/app/models/__init__.py                     + InferenceProfile import/__all__
backend/alembic/versions/a1b2c3d4e5f6_*.py          phase-5 migration (inference_profiles)
backend/app/schemas/key_request.py                  ApprovalConstraints, KeyRequestCreate/Reject,
                                                    InferenceProfileRefOut, KeyRequestOut,
                                                    ProvisionedKeyOut, KeyRequestResult
backend/app/services/provisioning.py                provision_for_request (profiles→key→audit)
backend/app/api/key_requests.py                     POST / GET (scoped) / GET{id} / approve / reject
backend/app/api/cost_centres.py                     archive cascade (reject pending + revoke keys)
backend/app/main.py                                 register key_requests router
backend/tests/test_key_requests.py                  22 L3 cases
backend/tests/test_migrations.py                    migrate-up-from-empty round trip
frontend/src/features/keyRequests/{types,api}.ts    typed client + TanStack hooks
frontend/src/components/TokenReveal.tsx             one-time token + setup instructions (copy)
frontend/src/pages/KeyRequestsPage.tsx              role-adaptive request/approve/reject + token
frontend/src/pages/KeyRequestsPage.test.tsx         11 Vitest cases
frontend/src/{App.tsx,components/AppLayout.tsx,App.css,mocks/handlers.ts,test/setup.ts}  wired in
```

### Validation

- Backend: **90 passed**, **0 warnings** (68 prior + 22 key-request L3; the migration round-trip counts within). Migration applied to the live dev DB (`alembic current` → `a1b2c3d4e5f6 (head)`).
- Frontend: `npm run build` (tsc strict + vite, 93 modules) clean; **22 Vitest tests** pass (11 prior + 11 new).
- **Live stack curl/Python sweep (`:8000`) — all green:** ccowner1 auto-approval → 201 + token + both CC profiles created; dev1 → pending; dev1 approve attempt → 403; admin approve with overrides (haiku-only, rolling_limit 25, expiry 30) → 200 + token; dev1 list → own-only, **no `bearer_token`** field; duplicate request → 409; invalid model on approve → 400; archive cascade → pending request rejected (approved requests retained, their keys revoked).

### Retro

**What went well**
- The P1–P4 frozen-contract + two-parallel-agents pattern held at larger scope: backend (model+migration+API+cascade+tests) and frontend (client+page+token+tests) integrated with **zero interface drift** — both green on the orchestrator's first full run, and the live sweep passed first try. The `{request, key}` envelope made "token shown once, only on provisioning" fall out cleanly on both sides.
- Resolving the token-handoff ambiguity from the canonical `design.md` §4.1 **before** freezing the contract avoided a mid-build redesign — auto-approval is the clean single-actor demo path.
- Closed three long-standing carry-forwards in one phase: the CC-archive cascade (open since P3) and the Alembic migrate-up-from-empty test (open since P1).

**What bit us (and the lesson)**
- **Orchestrator curl sweep wasted a run on a shell-quoting typo** (a stray `»` glyph aborted variable assignment; the "duplicate" check then returned 422-on-empty-UUID, not the real 409). **Lesson: for multi-step authed API sweeps, drive them from a stdlib Python script (urllib) rather than chained `curl`+inline-python — the quoting/escaping surface in bash is where the bug was, not the app.** Re-run via script passed cleanly.
- **Browser render still unverified** — Chrome extension not connected (as P1–P3). The key-request UI, `TokenReveal` copy button and setup-instruction snippets are covered by build + RTL/MSW only; pixels unconfirmed. Long-standing gap, now spanning every frontend phase.
- Live sweep left residual dev-DB rows (an archived `CC-P5B-*`, its revoked keys). Harmless local residue, consistent with P3; the idempotent seed won't remove it.

**Carry-forward for Phase 6**
- Phase 6 (Key Management & Developer Dashboard) builds `GET /api/keys` (scoped), `revoke`, `regenerate`, `PATCH constraints`. **The developer-obtains-own-token recovery path lands here** via `regenerate` (`aws.reset_key`) — Phase 5 only surfaces the token to whoever performs the provisioning action.
- Reuse `provision_for_request`'s patterns and the shared `app/core/request.py::client_ip` helper + `record_audit`.
- `key.stopped`/`key.restarted` audit actions and `lifetime_spend` updates are Phase 7 (budget enforcement) — `keys.lifetime_spend` currently seeds at 0 and nothing updates it yet.
- The archive cascade now revokes keys but there's no UI to *see* revoked keys until the Phase 6 dashboard — verify the cascade visually once `GET /api/keys` exists.
- `usage_snapshots`/`pricing_cache` tables still deferred to Phase 7; `inference_profiles` now exists and is populated on approval.

### Post-review hardening (full review before Phase 6)

A full backend + frontend review was run before starting Phase 6 and every finding was fixed (no blockers were found — the review confirmed the architecture, RBAC, and the token-never-stored invariant were sound). Changes:

**Backend** (now **93 backend tests**, 0 warnings):
- **AWS/DB consistency on failure** (the main gap): `provision_for_request` previously mutated the AWS layer (profiles, key) *before* the DB commit with no compensation — a mid-provision or commit-time failure left orphaned AWS state and could make an approval un-retryable (`DuplicateProfileError`). Now tracked + best-effort undone via `compensate_aws(...)` (delete created profiles, revoke key) on any failure; introduced `ProvisionOutcome`. New test drives a failing mock and asserts 502 + compensation (mock profile index empties).
- **Commit-time one-active-key race**: `IntegrityError` at commit (vs. the partial unique index) now maps to 409 (with AWS compensation), not a 500.
- **`get_db` rolls back on exception** (was relying on `close()`); explicit and clearer.
- **403 vs 404 consistency**: added `_can_see` — approve/reject now return **404** when the actor can't see the request (existence hidden, matching GET) and **403** only when they can see it but aren't a reviewer (e.g. the request's own developer). Two RBAC tests updated + an own-developer-403 test and an other-developer-404 test added.
- **Empty-allowed-models guard** → 400.
- **Factored `_client_ip`** out of both routers into `app/core/request.py::client_ip` (closes the duplication carry-forward early).
- Added a `?status=` filter test (endpoint existed, was untested).

**Frontend** (now **24 Vitest tests**, build clean):
- **Token-loss guard (HIGH)**: `TokenReveal` registers a `beforeunload` handler while shown + a prominent "navigate away and this token is gone — you'd need to regenerate" warning. (In-app router-blocker noted as a TODO pending a data-router migration.)
- **Silent-loss-on-null-key (MED)**: approve/auto-approve now treat a missing `key` as an error instead of silently closing the panel; the developer create form only shows `TokenReveal` when `status==='approved' && key`.
- **Mock user IDs standardised to strings** (removed the latent number/string mismatch).
- **Type tightening**: `KeyRequestStatus` union for `status`; mock `makeProvisionedKey` now derives `expires_at` from `expiry_days`.
- **TokenReveal polish**: clipboard write wrapped in try/catch with an error state; second copy button for the `AWS_BEARER_TOKEN_BEDROCK=` line; inline styles → CSS classes.
- Stronger tests: reject asserts the POST body carries `rejection_reason`; new tests for token/env-var rendering, developer-not-seeing-reviewer-controls, and clipboard copy (+ standalone `TokenReveal.test.tsx`).

**Still open / accepted:** in-app (SPA) navigation away from a shown token is mitigated by the warning + `beforeunload` but not hard-blocked (needs a React Router data router); the AWS-compensation is best-effort by design (a residual orphan beats masking the original error) and will be reconciled against real AWS in Phase 11.
