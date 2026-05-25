# Claude Code AWS Bedrock Manager — High-Level Requirements

## 1. Overview

A web application that serves as a self-service management control plane for provisioning and managing Claude Code access via AWS Bedrock within an organisation. The application automates all underlying cloud configuration — no manual cloud console steps are required after initial infrastructure setup.

### Context

Claude Code can connect directly to AWS Bedrock. Developers need credentials (a key/token) which they configure locally via environment variables. Once configured, Claude Code works immediately against the organisation's Bedrock instance.

This platform automates the creation, approval, distribution, and lifecycle management of those credentials.

---

## 2. User Roles

A user can hold multiple roles simultaneously (e.g., a Cost Centre Owner can also be a Developer with their own keys).

### 2.1 Administrator

**Concern:** Governance, security, and organisational oversight. Ensures the platform is configured correctly, controls who has access, and maintains visibility across all cost centres. Acts as the ultimate authority.

- Designated list of admins (configured in the system)
- Configures global platform settings (region, model access, policies)
- Creates cost centres
- Assigns one or more Cost Centre Owners to each cost centre
- Can approve/reject any key request (bypassing the Cost Centre Owner)
- Views usage dashboards and cost reports across all cost centres
- Manages users and their access
- Can revoke any key
- Sets global defaults for model restrictions and key policies

### 2.2 Developer

**Concern:** Getting access to Claude Code quickly and with minimal friction so they can do their work. They don't want to manage infrastructure or worry about budgets — they just want a working key.

- Logs in to the self-service portal
- Can hold **multiple keys simultaneously** (e.g., keys for different cost centres)
- Requests a key by selecting a **cost centre** from the list of available cost centres
- Views their own active keys, usage, and limit status
- Copies key + setup instructions to configure Claude Code locally
- Can **self-deactivate** any of their own keys (e.g., when leaving a cost centre)
- Can see when they've been stopped (limit reached) and when tokens become available again

### 2.3 Cost Centre Owner

**Concern:** Managing the cost and usage of Claude Code within their cost centre(s). They own the budget and need to ensure developers are using it responsibly. They decide who gets access and what limits apply.

A cost centre can have **multiple Cost Centre Owners** (e.g., a team lead and a finance lead both managing the same cost centre).

- Created/assigned by an Administrator for one or more cost centres
- Does not necessarily need a Bedrock key themselves (but can also be a Developer)
- **Approves or rejects** developer key requests for their cost centre(s)
- **Manages per-key constraints** when approving a developer:
  - Token limit over a configurable rolling period (number of days)
  - Total token budget for the key's lifetime
  - Which models the key can access (e.g., Sonnet only, no Opus)
  - Key expiration duration
- **Configures request defaults** for their cost centre(s):
  - Default allowed models, rolling limit, rolling period, lifetime budget, and expiry date
  - Expiry date is a **hard date** representing the project end — not a relative duration
  - Defaults pre-populate the approval form; the CCO can still override per request
  - Admins can also set/edit these defaults
- Can modify constraints on existing active keys
- Can revoke keys for developers in their cost centre
- Manages the overall cost centre budget (total cap across all keys in the cost centre)
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
2. Developer selects a **cost centre** (from list of existing cost centres)
3. Developer optionally enters a justification/description
4. Request enters **Pending Approval** state
5. The **Cost Centre Owner** for that cost centre is notified
6. Cost Centre Owner reviews and approves/rejects the request
7. On approval, the system **automatically** provisions the key, tagged with the cost centre code for cost attribution
8. Developer is notified, key is displayed with setup instructions
9. On rejection, developer is notified with reason

**Note:** An Administrator can also approve any key request directly, bypassing the Cost Centre Owner.

**Auto-approval:** If the requesting developer is themselves a Cost Centre Owner of the target cost centre, the request is created already approved (no separate review step) — they set their own constraints at request time.

**Key Constraints (set by Cost Centre Owner at approval time):**
- Token limit over a configurable rolling period (number of days, e.g., 50k tokens over 7 days)
- Total token budget for the key's lifetime
- Allowed models (e.g., Sonnet and Haiku only)
- Expiry date — defaults to the cost centre's project end date; editable by CCO per key
- Once the rolling period limit is reached, **key is stopped** until sufficient tokens become available as older usage falls outside the rolling window
- Usage tracked and attributed to the cost centre
- Cost centre-level budget applies across all keys in the cost centre

#### 3.1.3 Developer Dashboard
- View all active keys — developer can hold multiple simultaneously
- See key status: Active, Expired, Revoked, Stopped (limit reached), Pending Approval
- **Limit visibility**: for each key, show current usage vs limit within the rolling period, and when tokens become available again if stopped
- View usage metrics per key (token consumption, cost estimate)
- Rotate/regenerate a key
- **Self-deactivate** any of their own keys
- Revoke/delete own keys

### 3.2 Admin Control Plane

#### 3.2.1 Request Management
- View all pending key requests across all cost centres
- Approve/reject any key request (bypasses Cost Centre Owner)
- Bulk approve/reject

#### 3.2.2 Cost Centre Management
- Create new cost centres
- Assign/remove one or more Cost Centre Owners to/from each cost centre
- Deactivate cost centres (revokes all associated keys)

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

#### 3.2.5 Configuration
- Cloud account/region configuration
- Allowed Claude models (Opus, Sonnet, Haiku)
- Default key expiry policies
- Default key limit policies (can be overridden by Cost Centre Owners)
- Notification settings (Slack workspace, email server)

### 3.3 Cost Centre Owner Dashboard

#### 3.3.1 Approval & Key Configuration
- View pending key requests for their cost centre(s)
- Approve with constraints (set per-key limits: token limit over rolling period, total budget, models, expiry date)
- Reject with reason
- Modify constraints on existing active keys (e.g., increase/decrease limits)
- Revoke keys for developers in their cost centre

#### 3.3.1a Request Defaults
- **Configure request defaults** for each cost centre — pre-populated values applied to every new approval
- Default fields: allowed models, rolling limit (AUD), rolling period (days), lifetime budget (AUD), expiry date
- **Expiry date is a hard date** (project end date), not a relative number of days
- Defaults are applied at approval/auto-approval time; the CCO can override any field per request
- Admins can also view and edit a cost centre's request defaults
- Changes to defaults are audit-logged

#### 3.3.2 Cost Centre Usage View (scoped to their cost centre(s) only)
- **Developer activity table**: who has keys, last active, status, current usage vs limits
- **Model usage breakdown**: which models each developer is using (Opus/Sonnet/Haiku), with percentages
- **Token consumption**: input tokens, output tokens, total tokens per developer and in aggregate
- **Cost tracking**: estimated cost per developer, total cost centre cost, cost over time
- **Charts & Visualisations**:
  - Daily/weekly/monthly usage trends (line charts)
  - Cost burn-down / burn-rate chart
  - Model mix pie chart
  - Top consumers bar chart
- **Budget management**: set cost centre budget cap, view remaining budget, percentage used

#### 3.3.3 Alert Configuration
- Configure alerts via **email** and **Slack** (channel or DM)
- Slack workspace is configurable in the application settings
- Customisable thresholds:
  - Cost centre budget: notify at X% used (e.g., 50%, 80%, 100%)
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
- Key rotation: create new key, deactivate old key, notify developer
- Rolling period enforcement: usage is tracked over a sliding window of configurable days; oldest usage falls off as the window advances
- Developer self-deactivation: immediately deactivate the key and flag for cleanup

#### 3.4.4 Cost Tracking & Budget Enforcement
- Track usage per key, per developer, per cost centre
- Provide cost estimates based on token consumption and model pricing
- **Hard budget limits**: when a cost centre reaches its budget cap, all keys for that cost centre are automatically **stopped** (not slowed — fully blocked until sufficient usage falls outside the rolling window)
- **Soft alerts**: configurable threshold notifications before the hard limit is reached (e.g., at 50%, 80%)
- Keys are re-enabled automatically when older usage falls outside the rolling window and budget is available again, or if the Cost Centre Owner increases the budget
- Per-key limits also enforce hard stops within their rolling window

#### 3.4.5 Guardrails (Optional / Future)
- Content filtering per cost centre or globally
- Configurable by admin

---

## 4. Non-Functional Requirements

### 4.1 Security
- Bearer tokens are **never stored** — displayed once at creation/regeneration. A lost token is regenerated (invalidating the old one), not retrieved. No secret material persisted at rest as a result.
- All traffic encrypted in transit (TLS)
- Audit log of all key lifecycle operations (request, approve, reject, provision, revoke, stop, expire). Inference calls themselves are audited at the cloud layer (CloudTrail per IAM user), not in the app.
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
8. If developer finishes on the cost centre, they can self-deactivate the key
9. If usage limit is reached within the rolling period, key is stopped; portal shows when tokens become available again

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
| 2 | Approvers | Cost Centre Owners approve for their cost centres; Admins can bypass |
| 3 | Multi-region | Single region for now |
| 4 | Model restrictions | Yes — per-key, set by Cost Centre Owner at approval time |
| 5 | Budget limits | Hard stops (block keys at cap) with soft alerts before |
| 6 | Cost centre code validation | Free-text for now; future integration possible |
| 7 | Multi-account | Single account for now |
| 8 | Key expiration | Long-lived with configurable expiry (set by Cost Centre Owner per key) |
| 9 | Budget period | Rolling window of configurable days (not fixed calendar periods) |
| 10 | Scale | ~300 developers |
| 11 | Notifications | Email and Slack integration |
| 12 | Data residency | Australia (ap-southeast-2) in the first instance |
| 13 | Slack workspace | Configurable in app settings |
| 14 | Multiple keys per developer | Yes — can hold multiple cost centre keys simultaneously |
| 15 | Multiple Cost Centre Owners | Yes — a cost centre can have multiple owners |
| 16 | Role overlap | Users can hold multiple roles (e.g., Cost Centre Owner + Developer) |
| 17 | Throttle behaviour | Hard stop (blocked), not slowdown. Portal shows status and when tokens return |
| 18 | Model availability in region | Out of scope for app — initial AWS setup handled externally |

---

## 8. Open Questions

All questions resolved. No outstanding items.
