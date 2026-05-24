# Implementation Log

High-level progress tracker for the build. Complements [implementation-plan.md](implementation-plan.md) (the spec) by recording what was actually done, decisions taken during the build, and per-phase retros. Keep entries terse.

## Status at a glance

| Phase | Title | Status |
|-------|-------|--------|
| 1 | Project Scaffolding & Local Dev Environment | ✅ Done |
| 2 | Database Models & Hard-Coded Auth | ✅ Done |
| 3 | Cost Centre Management (Admin) | ⬜ Not started |
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
