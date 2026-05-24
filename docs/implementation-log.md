# Implementation Log

High-level progress tracker for the build. Complements [implementation-plan.md](implementation-plan.md) (the spec) by recording what was actually done, decisions taken during the build, and per-phase retros. Keep entries terse.

## Status at a glance

| Phase | Title | Status |
|-------|-------|--------|
| 1 | Project Scaffolding & Local Dev Environment | ✅ Done |
| 2 | Database Models & Hard-Coded Auth | ✅ Done |
| 3 | Cost Centre Management (Admin) | ✅ Done |
| 4 | AWS Integration Layer (Mock Only) | ⬜ Not started |
| 5 | Key Request & Approval Flow | ⬜ Not started |
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
