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

- **Key Provisioning Service** — Handles the request → approval → AWS provisioning flow. Creates IAM user, attaches model restriction policies, generates Bedrock API Key via `CreateServiceSpecificCredential`, returns bearer token.
- **Key Lifecycle Service** — Revocation (`UpdateServiceSpecificCredential` → Inactive), regeneration (`ResetServiceSpecificCredential`), expiry handling, and cleanup (`DeleteServiceSpecificCredential` + `DeleteUser`).
- **Cost Tracking Service** — Polls CloudWatch metrics per inference profile, calculates costs using cached pricing, updates usage snapshots in the DB.
- **Budget Enforcement Service** — Compares accumulated cost against rolling-period and lifetime budgets. Disables keys when CC budget is exceeded.
- **Pricing Service** — Fetches model pricing from AWS Price List API (`AmazonBedrockFoundationModels`), caches in DB, refreshes daily.

#### 3.2.3 AWS Integration Layer
Thin wrapper around `boto3` calls. Abstracted behind an interface so it can be swapped for a mock layer during local development.

**AWS services used:**
| Service | Purpose |
|---------|---------|
| **IAM** | Create/delete users, attach/detach policies, create/reset/deactivate service-specific credentials |
| **Bedrock** | Create inference profiles, model access configuration |
| **CloudWatch** | Poll `InputTokenCount`, `OutputTokenCount`, `CacheReadInputTokens`, `CacheWriteInputTokens` per inference profile |
| **Pricing** | Fetch current Bedrock model pricing via Price List Query API |
| **CloudTrail** | Audit trail (read-only — AWS logs automatically per IAM user) |

#### 3.2.4 Background Scheduler
A periodic task (every 1-2 minutes) that:
1. Queries CloudWatch for token metrics per active inference profile
2. Calculates cost using cached pricing rates
3. Updates usage snapshots in the database
4. Checks budgets and disables keys if thresholds are exceeded

### 3.3 Database (PostgreSQL)

Stores all application state. No secrets — bearer tokens are never persisted (displayed once on creation/regeneration).

**Core entities:**

| Entity | Description |
|--------|-------------|
| `users` | Platform users with role assignments (admin, developer, CCO) |
| `cost_centres` | Budget unit with owner assignments, status, budget cap |
| `keys` | Bedrock API Key metadata — IAM username, credential ID, status, expiry, model restrictions. No bearer token stored. |
| `key_requests` | Approval workflow — request, approval/rejection, constraints set by approver |
| `usage_snapshots` | Periodic cost/token data per inference profile, accumulated over rolling periods |
| `pricing_cache` | Current model pricing from AWS Price List API (refreshed daily) |
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

    loop Every 1-2 minutes
        Sched->>CW: GetMetricStatistics per inference profile
        CW-->>Sched: InputTokenCount, OutputTokenCount, Cache tokens
        Sched->>Sched: Calculate cost (tokens × cached pricing)
        Sched->>DB: Update usage_snapshots
        Sched->>DB: Check CC budget (rolling + lifetime)
        alt Budget exceeded
            Sched->>AWS: UpdateServiceSpecificCredential(Status=Inactive)
            Sched->>DB: Update key status → "Stopped"
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
- IAM policies (model restrictions per user)
- Application inference profiles (one per cost centre)
- CloudWatch metrics (read-only — populated automatically by Bedrock)

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
- **IAM policy enforcement** — model restrictions enforced at AWS layer, not app layer
- **Audit trail** — all actions logged in app DB; all Bedrock calls logged in CloudTrail per IAM user
- **PoC auth** — hardcoded users (production: corporate SSO via OIDC/SAML)
- **Key expiration** — built-in via `credential-age-days`; enforceable via SCP

---

## 7. Related Documents

- [Requirements](REQUIREMENTS.md) — Full functional and non-functional requirements
- [Design Decisions](design-decisions.md) — All 11 design decisions with rationale
- [Research](../research/) — Supporting research on AWS Bedrock, IAM, cost tracking, and more
