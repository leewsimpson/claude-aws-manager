# Implementation Plan

High-level development sequence for the Claude Code AWS Bedrock Manager PoC. Each phase builds on the previous — dependencies flow top-down.

---

## Phase 1 — Project Scaffolding & Local Dev Environment

**Goal:** Skeleton project that runs locally with `docker compose up`.

- [ ] Initialise monorepo structure (`/backend`, `/frontend`, `/docker`)
- [ ] Backend: FastAPI project with health endpoint, Pydantic settings, project config (Poetry/uv)
- [ ] Frontend: React + Vite + TypeScript project with proxy to backend
- [ ] PostgreSQL service with initial empty schema
- [ ] Docker Compose: backend + frontend + db, all wired together
- [ ] SQLAlchemy + Alembic setup (engine, session, migration scaffold)
- [ ] Verify: `docker compose up` → frontend loads, hits backend health endpoint, backend connects to db

**Outputs:** Running local stack with no business logic.

---

## Phase 2 — Database Models & Hard-Coded Auth

**Goal:** Core domain tables and PoC authentication so all subsequent work has a user context.

- [ ] Database models (SQLAlchemy):
  - `User` (id, username, display_name, role — admin/developer/cco)
  - `CostCentre` (id, code, name, budget_cap, status — active/archived)
  - `CostCentreOwner` (user_id, cost_centre_id — many-to-many)
  - `KeyRequest` (id, developer_id, cost_centre_id, status, justification, rejection_reason, constraints JSON)
  - `ProvisionedKey` (id, key_request_id, developer_id, cost_centre_id, iam_username, credential_id, status, expiry, constraints JSON)
  - `AuditLog` (id, actor_id, action, resource_type, resource_id, metadata JSON, timestamp)
- [ ] Alembic initial migration
- [ ] Seed data: hard-coded users (`admin/admin`, `dev1/dev1`, `dev2/dev2`, `ccowner1/ccowner1`)
- [ ] Hard-coded auth: login endpoint (username/password check against seed data), JWT token issuance
- [ ] Auth middleware: extract user from JWT, inject into request context
- [ ] Auth dependency: `get_current_user`, role-checking decorators/dependencies
- [ ] Frontend: login page, auth context/provider, protected route wrapper

**Outputs:** Users can log in, JWT protects all API routes, role context available everywhere.

---

## Phase 3 — Cost Centre Management (Admin)

**Goal:** Admins can create and manage cost centres — the organisational unit everything else hangs off.

- [ ] API endpoints:
  - `POST /api/cost-centres` — create cost centre
  - `GET /api/cost-centres` — list all (admin sees all; devs see non-archived)
  - `PATCH /api/cost-centres/{id}` — update (name, budget cap)
  - `POST /api/cost-centres/{id}/archive` / `unarchive`
  - `POST /api/cost-centres/{id}/owners` — assign CCO
  - `DELETE /api/cost-centres/{id}/owners/{user_id}` — remove CCO
- [ ] Frontend: Admin → Cost Centre management page (CRUD, assign owners)
- [ ] Frontend: cost centre list visible to developers (for key request flow)

**Outputs:** Admins can create cost centres and assign owners. Foundation for key requests.

---

## Phase 4 — AWS Integration Layer (Mock + Real)

**Goal:** Abstracted AWS service layer that the rest of the app calls. Mock by default, real AWS behind a config flag.

- [ ] Define AWS service interface (protocol/ABC):
  - `provision_key(iam_username, model_policy, expiry_days) → (credential_id, bearer_token)`
  - `revoke_key(iam_username, credential_id)`
  - `disable_key(credential_id)` / `enable_key(credential_id)`
  - `reset_key(credential_id) → new_bearer_token`
  - `update_model_policy(iam_username, allowed_models)`
  - `create_inference_profile(cost_centre, model) → profile_arn`
  - `get_usage_metrics(inference_profile_arn, period) → token_counts`
- [ ] Mock implementation: returns fake credential IDs/tokens, stores state in-memory
- [ ] Real implementation: boto3 calls (IAM CreateUser, AttachUserPolicy, CreateServiceSpecificCredential, etc.)
- [ ] Config switch: `AWS_MODE=mock|real` environment variable
- [ ] Unit tests for mock layer

**Outputs:** All AWS operations abstracted. App code never calls boto3 directly.

---

## Phase 5 — Key Request & Approval Flow

**Goal:** End-to-end key lifecycle — request, approve/reject, provision, display token.

- [ ] API endpoints:
  - `POST /api/key-requests` — developer submits request (select cost centre, justification)
  - `GET /api/key-requests` — list requests (scoped: dev sees own, CCO sees their CCs, admin sees all)
  - `POST /api/key-requests/{id}/approve` — CCO/admin approves (with constraints: models, rolling limit, lifetime budget, expiry)
  - `POST /api/key-requests/{id}/reject` — CCO/admin rejects (with reason)
  - Auto-approval logic: if requester is CCO of the target cost centre, skip approval
- [ ] On approval → call AWS layer to provision key → store credential_id + iam_username in DB → return bearer token (once)
- [ ] Validation: one active key per developer per cost centre
- [ ] Audit log entries for all state transitions
- [ ] Frontend — Developer:
  - "Request Key" flow (select CC, enter justification)
  - Pending request status view
  - Token display on approval (copy-to-clipboard, setup instructions)
- [ ] Frontend — CCO:
  - Pending requests list for their cost centres
  - Approve modal (set constraints) / Reject modal (enter reason)
- [ ] Frontend — Admin:
  - All pending requests view, bulk approve/reject

**Outputs:** Full request→approval→provisioning flow. Developer gets a bearer token and setup instructions.

---

## Phase 6 — Key Management & Developer Dashboard

**Goal:** Developers and CCOs can view, manage, and revoke active keys.

- [ ] API endpoints:
  - `GET /api/keys` — list keys (scoped by role)
  - `POST /api/keys/{id}/revoke` — revoke (developer revokes own; CCO/admin revokes any in scope)
  - `POST /api/keys/{id}/regenerate` — reset credential, return new token (once)
  - `PATCH /api/keys/{id}/constraints` — CCO updates constraints on active key
- [ ] Revocation → call AWS layer (delete IAM user, cleanup) → update DB status
- [ ] Regeneration → call AWS layer (ResetServiceSpecificCredential) → display new token
- [ ] Frontend — Developer Dashboard:
  - All active keys (one per CC), with status badges (Active, Expired, Revoked, Stopped, Pending)
  - Key details: cost centre, constraints, current spend vs limits, expiry
  - Revoke / Regenerate actions
  - Setup instructions per key (env vars, modelOverrides JSON)
- [ ] Frontend — Admin Key Management:
  - All keys across org, search/filter by developer/CC/status
  - Revoke any key

**Outputs:** Developers have a functional dashboard. Keys can be managed through their full lifecycle.

---

## Phase 7 — Cost Tracking & Budget Enforcement

**Goal:** Track token usage, calculate costs, enforce rolling and lifetime budgets.

- [ ] Usage data models:
  - `UsageSnapshot` (key_id, cost_centre_id, model, input_tokens, output_tokens, cost, timestamp)
- [ ] Pricing config: model → price-per-token (input/output), loaded from config file
- [ ] Background polling task (APScheduler or FastAPI background):
  - Every 5 minutes: call AWS layer `get_usage_metrics` for each active inference profile
  - Calculate cost (tokens × pricing)
  - Store usage snapshots
  - Check per-key rolling limit → disable key if exceeded
  - Check per-key lifetime budget → disable key if exceeded
  - Check cost centre budget cap → disable all CC keys if exceeded
  - Re-enable keys when rolling window advances and spend drops below limit
- [ ] API endpoints:
  - `GET /api/keys/{id}/usage` — usage history for a key
  - `GET /api/cost-centres/{id}/usage` — aggregate usage for a CC
  - `GET /api/usage/summary` — admin-level summary across all CCs
- [ ] Developer dashboard: show current spend vs limits, "stopped" status, when budget available again
- [ ] CCO dashboard: cost centre spend vs budget cap

**Outputs:** Automated cost tracking with hard budget enforcement. Usage data flowing into the app.

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

## Phase 9 — Budget Alerts & Global Policies

**Goal:** Configurable threshold alerts and admin-level policy controls.

- [ ] Alert configuration model:
  - `AlertConfig` (cost_centre_id, alert_type, threshold_pct, enabled)
- [ ] Alert types: CC budget thresholds (50%/80%/100%), per-developer limit thresholds, key expiry reminders
- [ ] Alert engine: on each polling cycle, evaluate thresholds → create in-app alert records
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
- [ ] API: `GET /api/audit-log` (admin only, with filters)
- [ ] Frontend: Admin → Audit Log page
- [ ] Error handling & retry: boto3 calls wrapped with exponential backoff
- [ ] Graceful degradation: if AWS is unreachable, queue operations for retry

**Outputs:** Automated key expiry, complete audit trail, resilient AWS operations.

---

## Phase 11 — Integration Testing & Polish

**Goal:** Validate end-to-end against real AWS. Polish UX.

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

```
Phase 1  Scaffolding
   ↓
Phase 2  DB Models & Auth
   ↓
Phase 3  Cost Centre Management ←──────────────────┐
   ↓                                                │
Phase 4  AWS Integration Layer                      │
   ↓                                                │
Phase 5  Key Request & Approval Flow ───────────────┘
   ↓
Phase 6  Key Management & Developer Dashboard
   ↓
Phase 7  Cost Tracking & Budget Enforcement
   ↓
Phase 8  Dashboards & Visualisations
   ↓
Phase 9  Budget Alerts & Global Policies
   ↓
Phase 10 Lifecycle Automation & Audit
   ↓
Phase 11 Integration Testing & Polish
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
