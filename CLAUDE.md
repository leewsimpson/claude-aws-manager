# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current State

This repo is **documentation/planning only — no application code exists yet**. The `/docs` and `/research` folders are the canonical specification; the PoC is to be built against them following `docs/implementation-plan.md` (Phases 1–11). When you start implementing, scaffold the monorepo structure described below rather than expecting it to already exist.

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

## Doc Map

- `docs/requirements.md` — functional + non-functional requirements, resolved decisions table.
- `docs/design.md` — C4 context/container diagrams, component layers, key sequence flows.
- `docs/data-model.md` — canonical DB schema.
- `docs/design-decisions.md` — the 11 numbered architectural decisions with rationale (read before changing architecture).
- `docs/implementation-plan.md` — the 11-phase build sequence with per-phase checklists.
- `docs/tech-spike.md` — hands-on AWS validation items to confirm before/during the build.
- `research/01`–`research/09` — supporting research on Bedrock config, IAM, model access, cost tracking, auth/SSO, guardrails, developer setup, and Bedrock API keys.
