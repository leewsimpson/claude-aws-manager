# Claude Code AWS Bedrock Manager — Design

## 1. Overview

A self-service web application that automates the provisioning, lifecycle management, and cost governance of Claude Code access via AWS Bedrock. The platform sits between developers who need Claude Code and the AWS Bedrock infrastructure that hosts it, providing a controlled approval and budget enforcement layer.

### System Context (C4 Level 1)

```mermaid
C4Context
    title System Context — Claude Code AWS Bedrock Manager

    Person(dev_browser, "Developer", "Requests keys, views usage via browser")
    Person(cco, "Cost Centre Owner", "Approves requests, manages budgets")
    Person(admin, "Administrator", "Governance, global config")
    Person(dev_terminal, "Developer", "Uses Claude Code in terminal")

    System(platform, "Claude Code AWS Bedrock Manager", "Approval, provisioning, cost tracking, budget enforcement")
    System_Ext(bedrock, "AWS Bedrock", "AI inference service (ap-southeast-2)")

    Rel(dev_browser, platform, "Request keys, view status")
    Rel(cco, platform, "Approve/reject, view dashboards")
    Rel(admin, platform, "Configure, manage")
    Rel(platform, bedrock, "IAM, CloudWatch, Price List API")
    Rel(dev_terminal, bedrock, "InvokeModel via bearer token")

    UpdateRelStyle(dev_terminal, bedrock, $lineColor="green", $textColor="green")
```

**Users** interact via the web UI to request keys, approve requests, and view dashboards.
**The platform** orchestrates AWS resources (IAM users, policies, Bedrock API Keys, inference profiles) and polls CloudWatch for usage data.
**Developers** use the provisioned bearer token in their terminal to run Claude Code, which calls AWS Bedrock directly. The platform does not sit in this path — it only provisions and governs the credentials.
**AWS Bedrock** is the AI inference service that developers call via Claude Code.

---

## 2. Container Diagram (C4 Level 2)

```mermaid
C4Container
    title Container Diagram — Claude Code AWS Bedrock Manager

    Person(user, "User", "Developer / CCO / Admin")
    Person(dev_terminal, "Developer", "Claude Code in terminal")

    System_Boundary(platform, "Claude Code AWS Bedrock Manager") {
        Container(frontend, "Frontend", "React + Vite, TypeScript", "SPA: developer, CCO, and admin dashboards")
        Container(backend, "Backend", "Python + FastAPI", "API, business logic, AWS orchestration, background polling")
        ContainerDb(db, "Database", "PostgreSQL", "Users, cost centres, keys, approvals, usage, pricing, audit log")
    }

    System_Ext(aws_iam, "AWS IAM", "User/policy management")
    System_Ext(aws_bedrock, "AWS Bedrock", "AI inference (ap-southeast-2)")
    System_Ext(aws_cw, "AWS CloudWatch", "Token usage metrics")
    System_Ext(aws_pricing, "AWS Price List API", "Model pricing")

    Rel(user, frontend, "HTTPS")
    Rel(frontend, backend, "REST API")
    Rel(backend, db, "SQLAlchemy")
    Rel(backend, aws_iam, "boto3 — create users, policies, credentials")
    Rel(backend, aws_bedrock, "boto3 — inference profiles")
    Rel(backend, aws_cw, "boto3 — poll token metrics")
    Rel(backend, aws_pricing, "boto3 — fetch model pricing")
    Rel(dev_terminal, aws_bedrock, "Bearer token — InvokeModel")

    UpdateRelStyle(dev_terminal, aws_bedrock, $lineColor="green", $textColor="green")
```

### Containers

| Container | Technology | Purpose |
|-----------|------------|---------|
| **Frontend** | React + Vite (TypeScript) | SPA serving developer, CCO, and admin dashboards. Communicates with backend via REST API. |
| **Backend** | Python + FastAPI | API server handling authentication, business logic, AWS orchestration, and background cost polling. |
| **Database** | PostgreSQL | Persistent storage for users, cost centres, key metadata, approvals, usage data, cached pricing, and audit logs. |

### Deployment

- **Local / PoC:** Docker Compose runs all three containers
- **Production:** Docker on ECS; PostgreSQL on RDS/Aurora

---

## 3. Component Descriptions

### 3.1 Frontend (React SPA)

The single-page application serves three role-based views. All users access the same app; the UI adapts based on the authenticated user's role(s).

| View | Users | Key Capabilities |
|------|-------|-------------------|
| **Developer Dashboard** | Developers | Request keys, view key status, copy setup instructions, view usage/spend per key, regenerate lost keys, revoke own keys |
| **CCO Dashboard** | Cost Centre Owners | Approve/reject key requests with constraints (model, budget, expiry), view per-developer usage within their cost centre(s), usage charts and trends, configure budget alert thresholds, archive/unarchive cost centres |
| **Admin Panel** | Administrators | Create cost centres, assign CCOs, manage global model restrictions, view cross-CC usage and cost reports, revoke any key, manage users |

### 3.2 Backend (FastAPI)

The backend is structured into four layers:

#### 3.2.1 API Layer
REST endpoints grouped by domain. Handles authentication (hardcoded users for PoC), request validation (Pydantic), and authorization (role-based access).

**Route groups:**
- `/api/auth` — Login, session management
- `/api/keys` — Request, approve, reject, revoke, regenerate keys
- `/api/cost-centres` — CRUD, archive/unarchive, budget configuration
- `/api/usage` — Usage metrics, cost data, charts data
- `/api/admin` — Global settings, user management, model restrictions

#### 3.2.2 Service Layer
Business logic decoupled from HTTP concerns. Orchestrates the key lifecycle:

- **Key Provisioning Service** — Handles the request → approval → AWS provisioning flow. Creates IAM user, attaches model restriction policy (including `bedrock:CallWithBearerToken` + inference profile access), creates/assigns inference profiles for the cost centre (creates on-demand if a new model is approved for a CC that doesn't yet have a profile for it), generates Bedrock API Key via `CreateServiceSpecificCredential`, returns bearer token + `modelOverrides` setup instructions.
- **Key Lifecycle Service** — Revocation (`UpdateServiceSpecificCredential` → Inactive), regeneration (`ResetServiceSpecificCredential`), expiry handling, and cleanup (`DeleteServiceSpecificCredential` + `DeleteUser`).
- **Cost Tracking Service** — Two data paths (see [design-decisions.md](design-decisions.md#12-per-key-usage-data-source)): (1) polls CloudWatch metrics per inference profile for CC-level budget enforcement, (2) parses model invocation logs for per-key attribution. Calculates costs using cached pricing, updates usage snapshots in the DB.
- **Budget Enforcement Service** — Compares accumulated cost against per-key rolling-period/lifetime limits and CC-level budget caps. Disables individual keys or all keys in a CC as needed.
- **Pricing Service** — Provides model pricing rates. Hardcoded for PoC; production fetches from AWS Price List API (`AmazonBedrockFoundationModels`), caches in DB, refreshes daily.

#### 3.2.3 AWS Integration Layer
Thin wrapper around `boto3` calls. Abstracted behind an interface so it can be swapped for a mock layer during local development.

**AWS services used:**
| Service | Purpose |
|---------|---------|
| **IAM** | Create/delete users, attach/detach policies (including `bedrock:CallWithBearerToken`, `bedrock:GetInferenceProfile`), create/reset/deactivate service-specific credentials |
| **Bedrock** | Create/delete inference profiles (one per CC per model), model access configuration |
| **CloudWatch** | Poll `InputTokenCount`, `OutputTokenCount`, `CacheReadInputTokens`, `CacheWriteInputTokens` per inference profile |
| **Bedrock Logs** | Model invocation logs (S3/CloudWatch Logs) for per-key attribution via IAM user identity |
| **Pricing** | Fetch current Bedrock model pricing via Price List Query API (hardcoded for PoC, API for production) |
| **CloudTrail** | Audit trail (read-only — AWS logs automatically per IAM user) |

#### 3.2.4 Background Scheduler
A periodic task (polling frequency defined in [design-decisions.md](design-decisions.md#6-budget-enforcement-timing)) that:
1. Queries CloudWatch for token metrics per active inference profile
2. Calculates cost using cached pricing rates
3. Updates usage snapshots in the database
4. Checks CC-level budgets and disables all keys in the CC if the budget cap is exceeded
5. Checks per-key rolling-period and lifetime limits; disables individual keys as needed
6. Sends alerts at configurable thresholds (50%, 80%, 100%)

### 3.3 Database (PostgreSQL)

Stores all application state. No secrets — bearer tokens are never persisted (displayed once on creation/regeneration).

**Core entities:**

| Entity | Description |
|--------|-------------|
| `users` | Platform users with role assignments (admin, developer, CCO) |
| `cost_centres` | Budget unit with owner assignments, status, budget cap |
| `keys` | Bedrock API Key metadata — IAM username, credential ID, status, expiry, model restrictions. No bearer token stored. |
| `key_requests` | Approval workflow — request, approval/rejection, constraints set by approver |
| `usage_snapshots` | Periodic cost/token data — CC-level from CloudWatch, per-key from invocation logs |
| `pricing_cache` | Current model pricing from AWS Price List API (refreshed daily) |
| `alert_configs` | Configurable alert thresholds per cost centre |
| `alert_history` | Record of triggered alerts (prevents duplicate notifications) |
| `audit_log` | Record of all state-changing actions (who did what, when) |

---

## 4. Key Flows

### 4.1 Key Provisioning (Happy Path)

```mermaid
sequenceDiagram
    actor Dev as Developer (browser)
    participant P as Platform
    actor CCO as Cost Centre Owner
    participant AWS as AWS (IAM)
    actor DevT as Developer (terminal)
    participant BR as AWS Bedrock

    Dev->>P: Request key (select cost centre)
    P->>P: Create key_request record
    P-->>CCO: Pending request notification (UI)
    CCO->>P: Approve (set model, budget, expiry constraints)
    P->>AWS: CreateUser (claude-{dev}-{cc})
    P->>AWS: AttachUserPolicy (model restrictions)
    P->>AWS: CreateServiceSpecificCredential
    AWS-->>P: ServiceApiKeyValue (bearer token)
    P->>P: Store key metadata (no token)
    P-->>Dev: Display token once + setup instructions

    Note over DevT: Developer copies token to terminal
    DevT->>BR: claude (InvokeModel via bearer token)
    BR-->>DevT: AI response
```

### 4.2 Budget Enforcement Loop

```mermaid
sequenceDiagram
    participant Sched as Background Scheduler
    participant CW as AWS CloudWatch
    participant DB as PostgreSQL
    participant AWS as AWS (IAM)

    loop Every polling cycle (see design-decisions.md §6)
        Sched->>CW: GetMetricStatistics per inference profile
        CW-->>Sched: InputTokenCount, OutputTokenCount, Cache tokens
        Sched->>Sched: Calculate cost (tokens × cached pricing)
        Sched->>DB: Update usage_snapshots
        Sched->>DB: Check per-key limits (rolling + lifetime)
        alt Per-key limit exceeded
            Sched->>AWS: UpdateServiceSpecificCredential(Status=Inactive)
            Sched->>DB: Update key status → "Stopped"
        end
        Sched->>DB: Check CC budget cap
        alt CC budget exceeded
            Sched->>AWS: Disable all keys in CC
            Sched->>DB: Update all key statuses → "Stopped"
        end
    end
```

### 4.3 Key Regeneration

```mermaid
sequenceDiagram
    actor Dev as Developer (browser)
    participant P as Platform
    participant AWS as AWS (IAM)

    Dev->>P: Click "Regenerate"
    P->>AWS: ResetServiceSpecificCredential
    AWS-->>P: New ServiceApiKeyValue
    Note over AWS: Old token invalidated immediately
    P-->>Dev: Display new token once
```

---

## 5. Infrastructure

### 5.1 AWS Account

Dedicated AWS account for Claude Code Bedrock usage (isolated from other workloads).

**Resources managed by the platform:**
- IAM users (one per developer per cost centre, naming: `claude-{dev}-{cc}`)
- IAM policies (model restrictions + inference profile access + `bedrock:CallWithBearerToken` per user)
- Application inference profiles (one per cost centre **per model** — e.g. CC with Sonnet + Haiku = 2 profiles)
- CloudWatch metrics (read-only — populated automatically by Bedrock when requests route through inference profiles)

### 5.2 Local Development

Docker Compose with three services:

```yaml
services:
  backend:     # FastAPI on port 8000
  frontend:    # React+Vite on port 5173 (proxies /api to backend)
  db:          # PostgreSQL on port 5432
```

Mock AWS layer for local dev; real AWS for integration tests and PoC demo.

---

## 6. Security Considerations

- **No secrets in the database** — bearer tokens are displayed once, never stored
- **Bedrock-scoped credentials** — API keys can only access Bedrock, not S3/EC2/etc
- **IAM policy enforcement** — model restrictions enforced at AWS layer, not app layer; exact model ARNs, not wildcards (see [design-decisions.md](design-decisions.md#13-iam-policy-model-specificity))
- **Audit trail** — all actions logged in app DB; all Bedrock calls logged in CloudTrail per IAM user
- **PoC auth** — hardcoded users with bcrypt-hashed passwords (production: corporate SSO via OIDC/SAML)
- **Key expiration** — built-in via `credential-age-days`; enforceable via SCP
- **JWT tokens** — short-lived (PoC: 24h expiry), stored in httpOnly cookies, include user ID and roles. No refresh tokens for PoC. On user deactivation, existing JWTs continue to work until expiry but all API calls check `is_active`.
- **Rate limiting** — login endpoint rate-limited (e.g., 5 attempts per minute per IP) to prevent brute-force. General API rate limiting deferred to production.
- **Slack webhook URLs** — stored as plain JSONB in `alert_configs` for PoC. Production should encrypt or use a secrets manager (see [data-model.md](data-model.md) alert_configs notes).

---

## 7. API Conventions

- **Pagination** — all list endpoints support `?page=1&page_size=50` query parameters (default: page 1, 50 items). Response includes `total`, `page`, `page_size`, and `items[]`.
- **Error format** — JSON: `{"detail": "message", "code": "ERROR_CODE"}`. HTTP status codes follow REST conventions.
- **Real-time updates** — PoC uses polling from the frontend (e.g., React Query refetch intervals). WebSocket/SSE deferred to production.

---

## 8. Key Algorithms

### 8.1 "Tokens Available Again" Calculation

When a key is stopped due to a rolling-period budget limit, the developer dashboard shows when tokens will become available. The algorithm:

1. Query `usage_snapshots` for the stopped key within the rolling window (`NOW() - rolling_period_days`)
2. Find the oldest snapshot(s) in the window that, if removed, would bring the rolling total below `rolling_limit`
3. The "available again" time = oldest such snapshot's `period_end` + `rolling_period_days`
4. Display as: "Budget available again in ~X hours" or a specific datetime

### 8.2 Inference Profile Lifecycle

Inference profiles are created on-demand, not eagerly:

1. When a key is approved for a CC + model combination, check if an active inference profile exists for that CC + model
2. If not, create one via `CreateInferenceProfile` and store in `inference_profiles`
3. Profiles are shared across all keys in the same CC for the same model
4. On CC archival, profiles are retained (not deleted) — they may contain CloudWatch metrics still needed for reporting
5. On CC unarchival, existing profiles are reused

---

## 9. Related Documents

- [Requirements](requirements.md) — Full functional and non-functional requirements
- [Data Model](data-model.md) — Database schema, entity definitions, and relationships
- [Design Decisions](design-decisions.md) — All design decisions with rationale
- [Tech Spike](tech-spike.md) — Hands-on validation items before PoC build
- [Research](../research/) — Supporting research on AWS Bedrock, IAM, cost tracking, and more
