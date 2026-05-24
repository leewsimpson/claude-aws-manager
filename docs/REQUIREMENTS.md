# Claude Code AWS Bedrock Manager — High-Level Requirements

## 1. Overview

A web application that serves as a self-service management control plane for provisioning and managing Claude Code access via AWS Bedrock within an organisation. The application automates all underlying cloud configuration — no manual cloud console steps are required after initial infrastructure setup.

### Context

Claude Code can connect directly to AWS Bedrock. Developers need credentials (a key/token) which they configure locally via environment variables. Once configured, Claude Code works immediately against the organisation's Bedrock instance.

This platform automates the creation, approval, distribution, and lifecycle management of those credentials.

### Terminology

A **cost centre** is the unit of budget ownership and access grouping in this system. It can represent a project, a department, a team, or any other organisational unit that owns a budget for Claude Code usage. Each cost centre has one or more Cost Centre Owners who manage its budget and approve access.

---

## 2. User Roles

A user can hold multiple roles simultaneously (e.g., a Cost Centre Owner can also be a Developer with their own keys).

### 2.1 Administrator

**Concern:** Governance, security, and organisational oversight. Ensures the platform is configured correctly, controls who has access, and maintains visibility across all cost centres. Acts as the ultimate authority.

- Designated list of admins (configured in the system)
- **Break-glass super admin**: a default super admin account exists for emergency access (configured outside the UI, e.g., environment variable or config file). No UI required for this configuration.
- Configures global platform settings (region, model access, policies)
- Creates cost centres
- Assigns one or more Cost Centre Owners to each cost centre
- Can approve/reject any key request (bypassing the Cost Centre Owner)
- Views usage dashboards and cost reports across all cost centres
- Manages users and their access
- Can revoke any key
- Sets global defaults for model restrictions and key policies
- When global model restrictions change (e.g., a model is removed), existing keys with access to the removed model have that model access revoked immediately

### 2.2 Developer

**Concern:** Getting access to Claude Code quickly and with minimal friction so they can do their work. They don't want to manage infrastructure or worry about budgets — they just want a working key.

- Logs in to the self-service portal
- Can hold **one key per cost centre**, but keys across **multiple cost centres** simultaneously
- Requests a key by selecting a **cost centre** from the list of all non-archived cost centres
- Views their own active keys, usage, and limit status
- Copies key + setup instructions to configure Claude Code locally
- Can **revoke** any of their own keys (e.g., when leaving a cost centre)
- Can see when they've been stopped (limit reached) and when tokens become available again
- Can **resubmit** a key request after rejection (no limit on resubmissions); rejection reason is visible
- When a developer is removed from the organisation (SSO deactivation), all their keys are automatically disabled

### 2.3 Cost Centre Owner

**Concern:** Managing the cost and usage of Claude Code within their cost centre(s). They own the budget and need to ensure developers are using it responsibly. They decide who gets access and what limits apply.

a cost centre can have **multiple Cost Centre Owners** (e.g., a project lead and a finance lead both managing the same cost centre).

- Created/assigned by an Administrator for one or more cost centres
- Does not necessarily need a Bedrock key themselves (but can also be a Developer)
- **Approves or rejects** developer key requests for their cost centre(s) — any single CCO can approve (consensus not required)
- If the CCO is also a Developer on the same cost centre, their own key requests are **auto-approved** (no separate approval needed)
- **Manages per-key constraints** when approving a developer:
  - Cost limit (in dollars) over a configurable rolling period (number of days)
  - Total cost budget (in dollars) for the key's lifetime
  - Which models the key can access (e.g., Sonnet only, no Opus)
  - Key expiration duration
- Can modify constraints on existing active keys (developer is notified of changes)
- Can revoke keys for developers in their cost centre
- Can **archive** their cost centre (disables all keys, auto-rejects pending requests; cost centre is retained but inactive)
- Can **unarchive** their own cost centre (restores previously active keys for developers still in the organisation)
- **Sets and manages the cost centre budget cap** (total dollar cap across all keys in the cost centre); can increase/top up at any time
- Has a dashboard scoped to their cost centre(s)
- Can view:
  - Which developers are using keys in their cost centre
  - Which models each developer is using (Opus, Sonnet, Haiku)
  - Token consumption per developer (input/output tokens)
  - Cost breakdown per developer and over time
  - Usage charts and trends (daily/weekly/monthly)
- **Configures alerts** (email and Slack) for their cost centre:
  - Budget threshold alerts (e.g., 50%, 80%, 100% of cost centre budget used)
  - Individual developer threshold alerts (e.g., developer exceeds X% of their limit)
  - Unusual usage spike alerts
  - Key expiry reminders
  - New key request notifications
  - Can choose which alerts they receive and at what thresholds

---

## 3. Functional Requirements

### 3.1 Developer Portal

#### 3.1.1 Authentication & Login
- **Production**: Corporate SSO (OIDC/SAML)
- **Proof of Concept**: Hard-coded usernames and passwords for simplicity
  - e.g., `admin/admin`, `dev1/dev1`, `ccowner1/ccowner1`
  - No external auth dependencies for the PoC

#### 3.1.2 Key Request Flow
1. Developer clicks "Request Key"
2. Developer selects a **cost centre** (from list of all non-archived cost centres)
3. Developer optionally enters a justification/description
4. If the developer is also a **Cost Centre Owner** for the selected cost centre, the key is **auto-approved** (no approval step needed)
5. Otherwise, request enters **Pending Approval** state
6. The **Cost Centre Owner(s)** for that cost centre are notified
7. Any single Cost Centre Owner reviews and approves/rejects the request
8. On approval, the system **automatically** provisions the key, tagged with the cost centre code for cost attribution
9. Developer is notified, key is displayed with setup instructions
10. On rejection, developer is notified with reason; developer may resubmit (no limit on resubmissions)

**Note:** An Administrator can also approve any key request directly, bypassing the Cost Centre Owner.

**Constraint:** A developer can only hold **one active key per cost centre**. They must revoke an existing key before requesting a new one for the same cost centre.

**Key Constraints (set by Cost Centre Owner at approval time):**
- Cost limit (in dollars) over a configurable rolling period (number of days, e.g., $50 over 7 days)
- Total cost budget (in dollars) for the key's lifetime
- Allowed models (e.g., Sonnet and Haiku only)
- Expiration duration (e.g., 90 days)
- Once the rolling period limit is reached, **key is stopped** until sufficient spend falls outside the rolling window
- Usage tracked and attributed to the cost centre
- cost centre-level budget cap applies across all keys in the cost centre

#### 3.1.3 Developer Dashboard
- View all active keys — one per cost centre, across multiple cost centres
- See key status: Active, Expired, Revoked, Stopped (limit reached), Pending Approval
- **Limit visibility**: for each key, show current spend vs limit within the rolling period, and when budget becomes available again if stopped
- View usage metrics per key (token consumption, cost)
- Revoke own keys
- Regenerate key credentials (issues a new bearer token; old one stops working immediately)
- View setup instructions (env vars to configure Claude Code — token shown only at creation/regeneration)

### 3.2 Admin Control Plane

#### 3.2.1 Request Management
- View all pending key requests across all cost centres
- Approve/reject any key request (bypasses Cost Centre Owner)
- Bulk approve/reject

#### 3.2.2 Cost Centre Management
- Create new cost centres
- Assign/remove one or more Cost Centre Owners to/from each cost centre
- Deactivate cost centres (revokes all associated keys)
- **Unarchive** a cost centre (restores previously active keys only for developers still in the organisation; expired keys remain expired)

#### 3.2.3 Key Management
- View all active keys across the organisation
- Revoke any key (triggers automated cloud resource cleanup)
- Set global policies: max key lifetime, allowed models, rate limits
- Search/filter by developer, cost centre code, status

#### 3.2.4 Cost & Usage Dashboard
- View aggregate usage and cost
- Break down costs by cost centre code
- Break down costs by developer/team
- Set budget alerts per cost centre or globally
- **Export CSV report** for a specified time period showing cost per cost centre (cost centre)

#### 3.2.5 Configuration
- Cloud account/region configuration
- Allowed Claude models (Opus, Sonnet, Haiku)
- Default key expiry policies
- Default key limit policies (can be overridden by Cost Centre Owners)
- Notification settings (Slack workspace, email server)

### 3.3 Cost Centre Owner Dashboard

#### 3.3.1 Approval & Key Configuration
- View pending key requests for their cost centre(s)
- Any single CCO can approve (multi-owner consensus not required)
- Approve with constraints (set per-key limits: cost limit over rolling period, total budget, models, expiry)
- Reject with reason (developer can resubmit)
- Modify constraints on existing active keys (e.g., increase/decrease limits) — developer is notified of changes
- Revoke keys for developers in their cost centre
- **Archive cost centre**: disables all keys in the cost centre, auto-rejects any pending requests; cost centre is retained in archived state (not deleted)
- **UnArchive cost centre**: restores previously active keys for developers still in the organisation; expired keys remain expired

#### 3.3.2 Cost Centre Usage View (scoped to their cost centre(s) only)
- **Developer activity table**: who has keys, last active, status, current spend vs limits
- **Model usage breakdown**: which models each developer is using (Opus/Sonnet/Haiku), with percentages
- **Token consumption**: input tokens, output tokens, total tokens per developer and in aggregate
- **Cost tracking**: cost per developer, total cost centre cost, cost over time
- **Charts & Visualisations**:
  - Daily/weekly/monthly usage trends (line charts)
  - Cost burn-down / burn-rate chart
  - Model mix pie chart
  - Top consumers bar chart
- **Budget management**: set cost centre budget cap (in dollars), view remaining budget, percentage used; can increase/top up at any time
- **Export CSV report** for a specified time period showing cost breakdown for their cost centre(s)

#### 3.3.3 Alert Configuration
- Configure alerts via **email** and **Slack** (channel or DM) — notifications only, no approval workflows via Slack
- Slack workspace is configurable in the application settings
- Customisable thresholds:
  - cost centre budget: notify at X% used (e.g., 50%, 80%, 100%)
  - Per-developer: notify when a developer exceeds X% of their key limit
  - Unusual spikes: notify on abnormal usage patterns
  - Key lifecycle: expiry reminders, new requests
- Enable/disable individual alert types
- Set alert recipients (self, or additional email addresses / Slack channels)

### 3.4 Automated Backend

The application must programmatically manage all cloud resources. No manual console interaction required after initial setup.

#### 3.4.1 Key Provisioning
- Automatically create credentials in the cloud when a key is approved
- Tag all resources with metadata (cost centre code, developer, created date, expiry)
- Provision must complete quickly (target: under 10 seconds for developer experience)

#### 3.4.2 Access Control
- Restrict keys to specific models as configured by admin
- Enforce model-level restrictions at the cloud layer (not just in the app)

#### 3.4.3 Key Lifecycle Management
- Automatic expiry enforcement (deactivate keys past their expiration)
- Revocation: clean up all associated cloud resources
- Rolling period enforcement: cost is tracked over a sliding window of configurable days; oldest spend falls off as the window advances
- SSO-based offboarding: when a user is deactivated in the identity provider, all their keys are automatically disabled
- Developer revocation: immediately deactivate the key and flag for cleanup

#### 3.4.4 Cost Tracking & Budget Enforcement
- Track cost per key, per developer, per cost centre (in dollars)
- Cost calculated from token consumption and model pricing (pricing sourced from AWS)
- **Three enforcement levels (all apply simultaneously):**
  1. **Per-key rolling period limit**: cost limit over a sliding window of N days; only that key is stopped when reached
  2. **Per-key lifetime budget**: total dollar cap for the key's lifetime; key is stopped permanently when reached
  3. **cost centre budget cap**: total dollar cap across all keys in the cost centre; **all keys in the cost centre are stopped** when reached
- **Soft alerts**: configurable threshold notifications before the hard limit is reached (e.g., at 50%, 80%)
- Per-key rolling limits: keys are re-enabled automatically when older spend falls outside the rolling window
- cost centre budget cap: keys are re-enabled if the Cost Centre Owner increases the budget
- Developer is notified when their key is stopped or re-enabled

#### 3.4.5 Guardrails (Optional / Future)
- Content filtering per cost centre or globally
- Configurable by admin

---

## 4. Non-Functional Requirements

### 4.1 Security
- All keys encrypted at rest and in transit
- Keys retrievable by the developer after creation (system is secured via authentication; no one-time-display restriction)
- Audit log of all key operations (create, approve, revoke, use) — retained indefinitely
- Audit logs accessible to Administrators only
- Cloud-level audit trail integration for API call auditing
- Role-based access control (RBAC) in the web application
- OWASP Top 10 compliance

### 4.2 Scalability
- Support ~300 developers and 1000s of keys
- Async key provisioning if needed

### 4.3 Reliability
- Handle cloud API failures gracefully (retry with backoff)
- Reconciliation to detect drift between app state and actual cloud state

### 4.4 Observability
- Application logging and monitoring
- Alerts on failed provisioning, expired keys, budget thresholds

---

## 5. Developer Experience (End-to-End Flow)

### Happy Path
1. Developer opens portal, clicks "Request Key"
2. Selects cost centre (e.g., `CC-1234`) and provides optional description
3. Sees "Pending Approval" status
4. Cost Centre Owner reviews and approves (sets per-key constraints)
5. Developer is notified: "Your key for CC-1234 is ready"
6. Developer copies setup instructions, pastes into terminal, runs `claude` — it works immediately
7. Usage is tracked against `CC-1234`; Cost Centre Owner can view dashboards
8. If developer is done with the cost centre, they can revoke the key
9. If usage limit is reached within the rolling period, key is stopped; portal shows when budget becomes available again

---

## 6. One-Time Initial Setup (Pre-requisites)

Before the app can function, an infrastructure administrator must:
1. Enable Bedrock model access in the target AWS account/region
2. Complete the Anthropic use-case form (required once per AWS account)
3. Create a service identity for the application with appropriate cloud permissions
4. Activate cost tracking mechanisms for cost centre-level attribution
5. Deploy the application

---

## 7. Resolved Decisions

| # | Decision | Resolution |
|---|----------|------------|
| 1 | Authentication | Corporate SSO (production); hard-coded users (PoC) |
| 2 | Approvers | Cost Centre Owners approve for their cost centres (any single CCO suffices); Admins can bypass |
| 3 | Multi-region | Single region for now |
| 4 | Model restrictions | Yes — per-key, set by Cost Centre Owner at approval time |
| 5 | Budget limits | Hard stops (block keys at cap) with soft alerts before |
| 6 | cost centre code validation | Free-text for now; future integration possible |
| 7 | Multi-account | Single account for now |
| 8 | Key expiration | Long-lived with configurable expiry (set by Cost Centre Owner per key) |
| 9 | Budget period | Rolling window of configurable days (not fixed calendar periods) |
| 10 | Scale | ~300 developers |
| 11 | Notifications | Email and Slack integration (alerts/notifications only; no approval workflows via Slack) |
| 12 | Data residency | Australia (ap-southeast-2) in the first instance |
| 13 | Slack workspace | Configurable in app settings |
| 14 | Keys per cost centre per developer | One key per cost centre per developer; multiple keys across different cost centres |
| 15 | Multiple Cost Centre Owners | Yes — a cost centre can have multiple owners; any one can approve |
| 16 | Role overlap | Users can hold multiple roles (e.g., Cost Centre Owner + Developer) |
| 17 | Throttle behaviour | Hard stop (blocked), not slowdown. Portal shows status and when budget returns |
| 18 | Model availability in region | Out of scope for app — initial AWS setup handled externally |
| 19 | Budget units | Dollars (not tokens) |
| 20 | Budget cap ownership | cost centre budget cap set and managed by CCO |
| 21 | Self-approval | CCO requesting a key for their own cost centre is auto-approved |
| 22 | Key rotation | Not required (removed from scope) |
| 23 | Key retrieval | Keys retrievable after creation (secured by authentication) |
| 24 | Audit log retention | Indefinite |
| 25 | Audit log access | Administrators only |
| 26 | Cost centre visibility | Developers can see all non-archived cost centres |
| 27 | User offboarding | Keys auto-disabled when user removed from SSO/identity provider |
| 28 | Archive behaviour | Archiving auto-rejects pending requests; unarchiving restores keys only for current org members |
| 29 | Global model changes | Removing a model globally revokes that model access from all existing keys |
| 30 | CCO delegation/absence | Admin bypass is sufficient; no separate escalation mechanism |
| 31 | Break-glass admin | Default super admin configured outside the UI (no UI needed) |
| 32 | Cost centre definition | A cost centre can represent a project, department, team, or any organisational unit |

---

## 8. Open Questions

All questions resolved. No outstanding items.
