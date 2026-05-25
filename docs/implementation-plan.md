# Implementation Plan

High-level development sequence for the Claude Code AWS Bedrock Manager PoC. Each phase builds on the previous — dependencies flow top-down.

**Mock-first strategy:** The entire app is built and demoed against the in-memory mock AWS layer (`AWS_MODE=mock`) first. The **real boto3 implementation is deferred to Phase 11** — everything before it runs fully local with no AWS account, no AWS cost, offline. This yields a clickable, end-to-end prototype at the **Phase 7 milestone** for early UX feedback, before any AWS integration work. The trade-off: a mock can bake in wrong assumptions about AWS behaviour (especially usage-data shape and timing), so the riskiest AWS assumptions are validated up front via a throwaway spike — see the "validate before you mock" note in Phase 4.

---

## Phase 1 — Project Scaffolding & Local Dev Environment

**Goal:** Skeleton project that runs locally with `docker compose up`.

- [x] Initialise monorepo structure (`/backend`, `/frontend`, `/docker`)
- [x] Backend: FastAPI project with health endpoint, Pydantic settings, project config (uv)
- [x] Frontend: React + Vite + TypeScript project with proxy to backend
- [x] PostgreSQL service with initial empty schema
- [x] Docker Compose: backend + frontend + db, all wired together
- [x] SQLAlchemy + Alembic setup (engine, session, migration scaffold)
- [x] Verify: `docker compose up` → frontend loads, hits backend health endpoint, backend connects to db

**Outputs:** Running local stack with no business logic.

---

## Phase 2 — Database Models & Hard-Coded Auth

**Goal:** Core domain tables and PoC authentication so all subsequent work has a user context.

- [x] Database models (SQLAlchemy):
  - `User` (id, username, display_name, email, password_hash, roles, is_active)
  - `CostCentre` (id, code, name, description, budget_cap, status, created_by)
  - `CostCentreOwner` (user_id, cost_centre_id, assigned_at, assigned_by)
  - `KeyRequest` (id, developer_id, cost_centre_id, status, justification, rejection_reason, reviewed_by, approved_constraints JSONB)
  - `Key` (id, key_request_id, developer_id, cost_centre_id, iam_username, credential_id, status, allowed_models, rolling_limit, rolling_period_days, lifetime_budget, lifetime_spend, expires_at)
  - `AuditLog` (id, actor_id, action, entity_type, entity_id, old_values JSONB, new_values JSONB, ip_address)
  - `GlobalSetting` (key, value JSONB, updated_by) — key-value store for region, allowed models, default key expiry/limits
- [x] Alembic initial migration
- [x] Seed data: hard-coded users (`admin/admin`, `dev1/dev1`, `dev2/dev2`, `ccowner1/ccowner1`) and `global_settings` defaults (region, allowed models, default expiry/limits)
- [x] Hard-coded auth: login endpoint (username/password check against seed data), JWT token issuance
- [x] Auth middleware: extract user from JWT, inject into request context
- [x] Auth dependency: `get_current_user`, role-checking decorators/dependencies
- [x] Frontend: login page, auth context/provider, protected route wrapper

**Outputs:** Users can log in, JWT protects all API routes, role context available everywhere.

---

## Phase 3 — Cost Centre Management (Admin)

**Goal:** Admins can create and manage cost centres — the organisational unit everything else hangs off.

- [x] API endpoints:
  - `POST /api/cost-centres` — create cost centre
  - `GET /api/cost-centres` — list all (admin sees all; devs see non-archived)
  - `GET /api/cost-centres/{id}` — fetch one (archived hidden from non-admins)
  - `PATCH /api/cost-centres/{id}` — update (name, description, budget cap)
  - `POST /api/cost-centres/{id}/archive` / `unarchive`
  - `POST /api/cost-centres/{id}/owners` — assign CCO (grants `cco` role)
  - `DELETE /api/cost-centres/{id}/owners/{user_id}` — remove CCO (strips `cco` if last)
  - `GET /api/users` — admin-only, supports the owner-assignment picker
- [x] First `audit_log` writer: reusable `app/core/audit.py::record_audit(...)`
- [x] Frontend: Admin → Cost Centre management page (CRUD, assign owners) + role-gated `AppLayout` nav
- [x] Frontend: cost centre list visible to developers (read-only, active-only)

> **Deferred (no writers yet):** archiving a CC does not yet cascade-disable keys / auto-reject pending requests — wired in Phase 5/6 when those tables get writers.

**Outputs:** Admins can create cost centres and assign owners. Foundation for key requests.

---

## Phase 4 — AWS Integration Layer (Mock Only)

**Goal:** Abstracted AWS service layer that the rest of the app calls, with a realistic in-memory mock. The **real boto3 implementation is deferred to Phase 11** — everything between here and there is built and demoed against the mock.

> **Validate before you mock.** Before building the mock, run the throwaway spikes in [tech-spike.md](tech-spike.md) (no app integration — raw AWS CLI/boto3) to confirm the *shape and timing* of the data the mock must imitate. Priorities: spike #1 (end-to-end provisioning + inference profile), spike #2 (CloudWatch metric latency/granularity — drives the polling-loop assumptions), spike #3 (invocation-log attribution shape). The mock's fake usage data should mirror what these spikes reveal, so UX feedback gathered against the mock holds up against real AWS.

- [x] Define AWS service interface (protocol/ABC) — `app/services/aws/base.py::AwsService`. Signatures refined from this indicative list (documented in implementation-log Phase 4): `provision_key` takes `cost_centre_code` + `allowed_models` (layer builds the IAM policy; `model_policy`→`allowed_models`); usage methods take explicit `start`/`end` window; `create_inference_profile → InferenceProfileRef(arn, name)`:
  - `provision_key(iam_username, cost_centre_code, allowed_models, expiry_days) → ProvisionedKey`
  - `revoke_key(iam_username, credential_id)`
  - `disable_key(credential_id)` / `enable_key(credential_id)`
  - `reset_key(credential_id) → new_bearer_token`
  - `update_model_policy(iam_username, allowed_models)`
  - `create_inference_profile(cost_centre_code, model_id) → InferenceProfileRef`
  - `delete_inference_profile(profile_arn)`
  - `get_usage_metrics(profile_arn, start, end) → TokenUsage`
  - `parse_invocation_logs(since) → list[KeyUsage]` (per-key attribution, see [design-decisions.md](design-decisions.md#12-per-key-usage-data-source))
- [x] Mock implementation (`MockAwsService`): returns fake credential IDs/tokens, stores state in-memory; `RealAwsService` is a Phase-11 stub (raises `NotImplementedError`)
- [x] **Realistic mock usage data:** `UsageSimulator` accrues plausible token counts over time per active key/profile (deterministic per-key rate, pause/resume on disable/enable, windowed CloudWatch + per-key invocation-log paths) so keys actually approach/cross limits. ⚠ tech-spike #2/#3 were **not** run (offline, no AWS account) — the usage *shape* is a documented assumption isolated in `usage.py`, to be reconciled in Phase 11.
- [x] Config switch: `AWS_MODE=mock|real` via `get_aws_service()` factory (only `mock` wired up until Phase 11)
- [x] Unit tests for mock layer (`tests/test_aws_mock.py`, 32 cases, pure/offline)

**Outputs:** All AWS operations abstracted behind the interface; app code never calls boto3 directly. The whole app can now be built and demoed offline against the mock.

---

## Phase 5 — Key Request & Approval Flow

**Goal:** End-to-end key lifecycle — request, approve/reject, provision, display token.

- [x] API endpoints:
  - `POST /api/key-requests` — developer submits request (select cost centre, justification)
  - `GET /api/key-requests` — list requests (scoped: dev sees own, CCO sees their CCs, admin sees all)
  - `POST /api/key-requests/{id}/approve` — CCO/admin approves (with constraints: models, rolling limit, lifetime budget, expiry)
  - `POST /api/key-requests/{id}/reject` — CCO/admin rejects (with reason)
  - Auto-approval logic: if requester is CCO of the target cost centre, skip approval
- [x] `InferenceProfile` model (id, cost_centre_id, model_id, profile_arn, profile_name, status) — provisioning needs to persist profiles created on approval
- [x] On approval → for each approved model, ensure a CC+model inference profile exists (create via AWS layer + persist if not) → call AWS layer to provision key → store credential_id + iam_username in DB → return bearer token (once)
- [x] Validation: one active key per developer per cost centre
- [x] Audit log entries for all state transitions
- [x] Frontend — Developer:
  - "Request Key" flow (select CC, enter justification)
  - Pending request status view
  - Token display on approval (copy-to-clipboard, setup instructions)
- [x] Frontend — CCO:
  - Pending requests list for their cost centres
  - Approve modal (set constraints) / Reject modal (enter reason)
- [x] Frontend — Admin:
  - All pending requests view (scoped to all CCs). _Bulk approve/reject deferred — single-request actions only for now._

> **Done beyond plan:** wired the **CC-archive cascade** (auto-reject pending requests + revoke active keys via the AWS layer) — the P3/P4 carry-forward. Added the **Alembic migrate-up-from-empty test** (P1/P2/P3 carry-forward).
>
> **Resolved during build:** provision-on-approval; the bearer token is returned **once** in the approve/auto-approve response. The developer-obtains-own-token recovery path is Phase-6 regenerate.

**Outputs:** Full request→approval→provisioning flow. Developer gets a bearer token and setup instructions.

---

## Phase 6 — Key Management & Developer Dashboard

**Goal:** Developers and CCOs can view, manage, and revoke active keys.

- [x] API endpoints:
  - `GET /api/keys` — list keys (scoped by role)
  - `POST /api/keys/{id}/revoke` — revoke (developer revokes own; CCO/admin revokes any in scope)
  - `POST /api/keys/{id}/regenerate` — reset credential, return new token (once)
  - `PATCH /api/keys/{id}/constraints` — CCO updates constraints on active key
- [x] Revocation → call AWS layer (delete IAM user, cleanup) → update DB status
- [x] Regeneration → call AWS layer (ResetServiceSpecificCredential) → display new token
- [x] Frontend — Developer Dashboard:
  - All keys (one per CC), with status badges (Active, Stopped, Revoked, Expired)
  - Key details: cost centre, constraints, spend vs limits (`lifetime_spend`; live usage Phase 7), expiry
  - Revoke / Regenerate actions
  - Setup instructions per key (env var name, modelOverrides JSON from inference_profiles)
- [x] Frontend — Admin Key Management:
  - All keys across org, filter by developer/CC/status

> **Resolved during build:** regenerate is dev-owner/admin only (the token is the developer's secret; CCO→403); revoke = dev-owner/CCO/admin; constraints = CCO/admin only. `GET /api/keys` returns a plain array (design.md §7 pagination stays a PoC-wide deferral).
  - Revoke any key

**Outputs:** Developers have a functional dashboard. Keys can be managed through their full lifecycle.

---

## Phase 7 — Cost Tracking & Budget Enforcement

**Goal:** Track token usage, calculate costs, enforce rolling and lifetime budgets.

- [x] Usage data models:
  - `UsageSnapshot` (key_id (nullable), inference_profile_id, model_id, source, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost, period_start, period_end)
  - `PricingCache` (model_id, model_name, input_price_per_1k, output_price_per_1k, cache prices, region)
  - (`InferenceProfile` model already added in Phase 5)
- [x] Pricing config: model → price-per-1K-tokens (input/output), in `app/services/pricing.py::PRICING`, seeded into `pricing_cache`
- [x] Background polling task (a dependency-free daemon thread, started in the FastAPI lifespan; pure `run_poll_cycle`):
  - On each cycle (frequency per [design-decisions.md](design-decisions.md#6-budget-enforcement-timing); demo-accelerated via env): call AWS layer `get_usage_metrics` for each active inference profile
  - Calculate cost (tokens × pricing)
  - Store usage snapshots (cloudwatch CC-level + invocation-log per-key)
  - Check per-key rolling limit → disable key if exceeded
  - Check per-key lifetime budget → disable key if exceeded
  - Check cost centre budget cap → disable CC keys if exceeded
  - Re-enable keys when rolling window advances and spend drops below limit
- [x] API endpoints:
  - `GET /api/keys/{id}/usage` — usage history for a key
  - `GET /api/cost-centres/{id}/usage` — aggregate usage for a CC
  - `GET /api/usage/summary` — admin-level summary across all CCs
- [x] Developer dashboard: live spend vs limits (meters), "stopped" reason banner + auto-resume note
- [x] CCO/Admin dashboard: cost centre spend vs budget cap + org usage summary

**Outputs:** Automated cost tracking with hard budget enforcement. Usage data flowing into the app.

---

## ⭐ Milestone — Clickable Local Prototype (end of Phase 7)

At this point the full core idea runs end-to-end, **completely local against the mock**: log in as any role → developer requests a key → CCO approves with constraints → token shown once with setup instructions → key appears on the developer dashboard → mock usage accrues → spend tracks against rolling/lifetime limits → key hard-stops when a limit or CC budget is exceeded.

**This is the feedback checkpoint** — demo it, gather UX feedback on the request/approval flow, constraint model, and dashboards before investing in richer visualisations (Phase 8) or any real AWS work (Phase 11). Phases 8–10 polish and extend; none of them require AWS.

---

## Phase 8 — Dashboards & Visualisations

**Goal:** Rich dashboard views for CCOs and Admins with charts and breakdowns.

- [ ] Charting library integration (e.g., Recharts, Chart.js, or similar)
- [ ] CCO Dashboard:
  - Developer activity table (keys, status, last active, spend vs limits)
  - Model usage breakdown per developer (Opus/Sonnet/Haiku percentages)
  - Token consumption table (input/output/total per developer)
  - Cost breakdown per developer and over time
  - Daily/weekly/monthly usage trend line charts
  - Cost burn-down / burn-rate chart
  - Model mix pie chart
  - Top consumers bar chart
  - Budget gauge (remaining budget, percentage used)
- [ ] Admin Dashboard:
  - Aggregate usage and cost across all CCs
  - Cost breakdown by cost centre
  - Cost breakdown by developer
  - Global budget/usage summary
- [ ] API endpoints to serve aggregated/time-series data for charts
- [ ] Date range selector for all dashboards

**Outputs:** Visual dashboards with charts and data tables for CCOs and Admins.

---

## Phase 8.5 — Developer CLI

**Goal:** A thin command-line client so developers manage tokens from the terminal — where Claude Code actually runs — without opening the browser. Scheduled after Phase 8, but it only depends on the Phase 5–7 endpoints (`retrieve`, `keys`, `usage`). It is a **pure REST API client**: no backend changes for the read/retrieve MVP, no business logic, and no token persisted beyond secure local storage.

- [ ] CLI scaffold (`/cli`) — packaged separately (Python via uv/pipx); talks to the backend REST API only
- [ ] `caws login` — username/password → JWT in `~/.config/caws/` (0600); mirrors PoC auth, leaving room for the production SSO device flow
- [ ] `caws keys` — list your keys with status and live rolling + lifetime spend vs limits
- [ ] `caws retrieve <id>` — `POST /keys/{id}/retrieve`; write the once-only token to the OS keychain (or a 0600 file), not stdout by default
- [ ] `caws env` — print `export AWS_BEARER_TOKEN_BEDROCK=…` for `eval "$(caws env)"`, sourced from secure local storage
- [ ] `caws regenerate <id>` — lost-token recovery path
- [ ] `caws status` — why a key stopped and when it resumes (reuses `GET /keys/{id}/usage`)
- [ ] Out of scope (stays web-only): request submission, approvals, CC/admin management

**Outputs:** Developers retrieve and refresh tokens straight into their environment from the terminal, with safer secret handling than browser copy-paste.

---

## Phase 9 — Budget Alerts & Global Policies

**Goal:** Configurable threshold alerts and admin-level policy controls.

- [ ] Alert configuration model:
  - `AlertConfig` (cost_centre_id, alert_type, threshold_pct, channels, channel_config, enabled)
  - `AlertHistory` (alert_config_id, cost_centre_id, alert_type, message, context JSONB, is_read, triggered_at)
- [ ] Alert types: CC budget thresholds (50%/80%/100%), per-developer limit thresholds, key expiry reminders
- [ ] Alert engine: on each polling cycle, evaluate thresholds → check `alert_history` to avoid duplicates → create new alert records
- [ ] In-app alert display (notification bell / alerts page) — email/Slack deferred to production
- [ ] API endpoints:
  - `GET/PUT /api/cost-centres/{id}/alerts` — CCO configures alert thresholds
  - `GET /api/alerts` — list triggered alerts (scoped by role)
- [ ] Admin global policies:
  - `GET/PUT /api/settings` — allowed models, default key expiry, default limits
  - When global model list changes → update IAM policies on all affected keys
- [ ] Frontend: CCO alert configuration, Admin settings page

**Outputs:** Configurable alerts surfaced in the UI. Admin can set global defaults and model restrictions.

---

## Phase 10 — Key Expiry, Lifecycle Automation & Audit

**Goal:** Automated housekeeping and full audit trail.

- [ ] Background task: check for expired keys → deactivate via AWS layer → update DB status
- [ ] Audit log:
  - All key operations already logged (Phase 5+6) — verify completeness
  - Admin-only audit log viewer: filterable by action, user, resource, date range
- [ ] API: `GET /api/audit-log` (admin only, with filters and pagination)
- [ ] Frontend: Admin → Audit Log page
- [ ] Graceful degradation: if AWS is unreachable, queue operations for retry (retry logic itself already in Phase 4)

**Outputs:** Automated key expiry, complete audit trail, resilient AWS operations.

---

## Phase 11 — Real AWS Implementation, Integration Testing & Polish

**Goal:** Implement the real AWS backend behind the Phase 4 interface, validate end-to-end against real AWS, polish UX.

- [ ] **Real AWS implementation** of the Phase 4 service interface: boto3 calls (IAM CreateUser, PutUserPolicy, CreateServiceSpecificCredential, CreateInferenceProfile, CloudWatch `get_metric_statistics`, invocation-log parsing, etc.)
- [ ] Basic retry logic: wrap boto3 calls with exponential backoff (e.g., `tenacity` library)
- [ ] Wire up `AWS_MODE=real` and confirm the full app works unchanged when switched from `mock` to `real`
- [ ] Reconcile any mock/real divergence surfaced here against assumptions baked in earlier (esp. usage-data shape from the Phase 4 spike)
- [ ] Integration test suite (pytest): runs against real AWS dev account
  - Provision a key, verify IAM user + policy created
  - Revoke a key, verify cleanup
  - Model restriction change, verify policy update
  - Usage metrics retrieval from CloudWatch
- [ ] End-to-end smoke test: request key → approve → copy token → configure Claude Code → invoke model → verify usage appears in dashboard
- [ ] UI polish: loading states, error handling, responsive layout, empty states
- [ ] Security review: OWASP Top 10 check, input validation, RBAC enforcement on all endpoints
- [ ] README with setup instructions, architecture overview, environment variables

**Outputs:** Validated PoC ready for demo with real AWS credentials.

---

## Dependency Graph

All phases below run against the **mock** AWS layer. Real AWS arrives only in Phase 11.

```
Phase 1  Scaffolding
   ↓
Phase 2  DB Models & Auth
   ↓
Phase 3  Cost Centre Management ←──────────────────┐
   ↓                                                │
Phase 4  AWS Integration Layer (mock only)          │
   ↓                                                │
Phase 5  Key Request & Approval Flow ───────────────┘
   ↓
Phase 6  Key Management & Developer Dashboard
   ↓
Phase 7  Cost Tracking & Budget Enforcement
   ↓
══ ⭐ Clickable local prototype — FEEDBACK CHECKPOINT ══
   ↓
Phase 8  Dashboards & Visualisations
   ↓
Phase 8.5  Developer CLI (thin API client over P5–P7 endpoints)
   ↓
Phase 9  Budget Alerts & Global Policies
   ↓
Phase 10 Lifecycle Automation & Audit
   ↓
Phase 11 Real AWS Implementation, Integration Testing & Polish
```

---

## Scope Reminder

**In PoC (Phases 1–11):**
- Hard-coded auth, real AWS provisioning, usage charts, budget alerts, key lifecycle

**Deferred to production:**
- Corporate SSO (OIDC/SAML)
- Email & Slack notifications (in-app only for PoC)
- CSV export
- Guardrails / content filtering
- SSO-based auto-offboarding
- Drift reconciliation
- Unusual usage spike detection

---

## Nice-to-Have Features (Post-PoC)

Features deferred from the PoC but tracked here with links to their source requirements. These can be picked up incrementally after the core PoC is validated.

| # | Feature | Source Requirement | Notes |
|---|---------|-------------------|-------|
| N1 | Corporate SSO (OIDC/SAML) | [REQ §3.1.1](requirements.md#311-authentication--login) | Replace hardcoded auth. Enables auto-offboarding. |
| N2 | Email notifications (AWS SES) | [REQ §3.3.3](requirements.md#333-alert-configuration) | Budget alerts, key approval/rejection, expiry reminders via email. |
| N3 | Slack notifications (webhooks) | [REQ §3.3.3](requirements.md#333-alert-configuration) | Budget alerts, key approval/rejection to Slack channels. |
| N4 | CSV export of usage data | [REQ §3.2.4](requirements.md#324-cost--usage-dashboard) | Export cost/usage reports for finance teams. |
| N5 | Guardrails / content filtering | [REQ §3.4.5](requirements.md#345-guardrails-optional--future) | Per-CC or global content filtering via Bedrock Guardrails. |
| N6 | SSO-based auto-offboarding | [REQ §4.1](requirements.md#41-security) | When user is deactivated in SSO, auto-disable all keys. |
| N7 | Drift reconciliation | [REQ §4.3](requirements.md#43-reliability) | Detect and fix mismatches between app DB and actual AWS state. |
| N8 | Unusual usage spike detection | [REQ §3.3.3](requirements.md#333-alert-configuration) | Anomaly detection on usage patterns. `usage_spike` alert type exists in schema as placeholder. |
| N9 | WebSocket/SSE real-time updates | [REQ §3.1.3](requirements.md#313-developer-dashboard) | Push approval status, usage updates to frontend without polling. |
| N10 | Full invocation log parsing | [Design Decision #12](design-decisions.md#12-per-key-usage-data-source) | If PoC uses proportional estimation, upgrade to full log parsing for accurate per-key attribution. |
| N11 | Pre-calculated "estimated remaining budget" | [Design Decision #6](design-decisions.md#6-budget-enforcement-timing) | Show developers projected budget depletion time on dashboard. |
| N12 | Adaptive polling frequency | [Design Decision #6](design-decisions.md#6-budget-enforcement-timing) | Tighten polling for CCs near their budget threshold. |
