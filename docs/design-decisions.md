# Design Decisions

Design decisions informed by the research in `/research/`. Decisions marked ✅ are resolved; others are still open.

---

## 1. Credential Strategy: What Type of Key Do We Give Developers? ✅ DECIDED

**Decision: Bedrock API Keys (long-term)**

Developers receive a single bearer token (`AWS_BEARER_TOKEN_BEDROCK`) generated via Bedrock's native API key feature. Under the hood, each long-term key creates an IAM user, giving us full IAM policy control with the simplest possible developer experience.

**Why this wins over alternatives:**
- vs **IAM User + Access Key**: Same IAM control underneath, but developer gets 1 token instead of 2 (key+secret). Keys are Bedrock-scoped only (can't access S3/EC2/etc if leaked). Key value not logged in CloudTrail.
- vs **STS Temporary Credentials**: Requirements demand "copy key + setup instructions" — temp creds that expire in hours are incompatible with this UX. Developers don't want credential refresh friction.

**What this gives us:**
- Single bearer token for developers: `export AWS_BEARER_TOKEN_BEDROCK=br-xxxxx`
- Model restrictions via IAM policies on the underlying user
- Revocation: `UpdateServiceSpecificCredential(Status=Inactive)` or `DeleteServiceSpecificCredential`
- Per-key cost tracking via unique IAM user identity in CloudTrail/invocation logs
- Built-in expiration: `--credential-age-days N` at creation time
- Programmatic creation: `iam:CreateServiceSpecificCredential` with `service-name bedrock.amazonaws.com`
- Bedrock-scoped only — cannot access other AWS services

**Accepted trade-offs:**
- AWS labels long-term keys as "for exploration" — this is a security recommendation, not a technical limitation. Acceptable for ~300 known internal developers with automated provisioning, revocation, and expiry.
- IAM user created under the hood — same 5,000/account limit applies, but fine for ~300 developers.

**Provisioning flow:**
```
CreateUser → AttachUserPolicy (model restrictions) → CreateServiceSpecificCredential → return bearer token
```

**See:** [research/09](../research/09-bedrock-api-keys-deep-dive.md), [research/01](../research/01-claude-code-bedrock-configuration.md), [research/02](../research/02-aws-iam-access-control.md)

---

## 2. Cost Tracking: How Do We Know What Each Key Has Spent? ✅ DECIDED

**Decision: CloudWatch metrics (real-time) + invocation logs (detailed breakdown), with app-calculated cost**

Two-layer approach:
1. **CloudWatch metrics per inference profile** for near-real-time CC-level token counts (InputTokenCount, OutputTokenCount)
2. **Model invocation logs** (S3/CloudWatch Logs) for per-key drill-down via IAM user identity

| Data source | What it gives us | Latency |
|-------------|-----------------|--------|
| CloudWatch Metrics (per inference profile) | CC-level token counts for budget enforcement | Near real-time |
| Model Invocation Logs | Per-key, per-request detail for drill-down and reconciliation | Minutes |
| AWS Cost Explorer (cost allocation tags) | CC-level dollar costs for finance/reporting | 24-48 hours |

**Sub-decisions (all resolved):**
- **Inference profiles:** One per cost centre **per model** (since each profile binds to a single model). If CC-1234 allows Sonnet + Haiku, that's 2 profiles. Claude Code's `modelOverrides` setting maps each model to its CC-specific profile ARN — confirmed working with bearer token auth (see below).
- **Polling frequency:** Every 5 minutes. Sufficient for budget enforcement; overshoot is bounded.
- **Cost calculation:** App-calculated (tokens × pricing). Cost Explorer has 24-48h lag — incompatible with rolling budget enforcement.
- **Pricing storage:** Config file, not hardcoded. Refreshed periodically. Start with hardcoded values for PoC, move to AWS Price List API later.

**Bearer token + inference profiles — CONFIRMED (May 2026):**
The Claude Code docs explicitly confirm that `AWS_BEARER_TOKEN_BEDROCK` and inference profile ARNs work together. The IAM configuration section even notes: *"This applies most often to `AWS_BEARER_TOKEN_BEDROCK` deployments, where the token's policy is typically narrower than a full IAM role."*

**Developer setup instructions** will include `modelOverrides` in the Claude Code settings file, mapping each allowed model to its CC's inference profile ARN:
```json
{
  "modelOverrides": {
    "claude-sonnet-4-6": "arn:aws:bedrock:ap-southeast-2:123456789012:application-inference-profile/cc1234-sonnet",
    "claude-haiku-4-5": "arn:aws:bedrock:ap-southeast-2:123456789012:application-inference-profile/cc1234-haiku"
  }
}
```

**See:** [research/04](../research/04-cost-tracking-budget-enforcement.md), [research/03](../research/03-aws-bedrock-model-access-setup.md), [research/08](../research/08-architecture-implementation-notes.md)

---

## 3. Model Restrictions: Where Is It Enforced? ✅ DECIDED

**Decision: IAM Policy on the underlying IAM user**

Since Bedrock API Keys create an IAM user underneath (Decision #1), we attach an IAM policy to that user restricting `bedrock:InvokeModel` to specific model ARNs. This is enforced at the AWS layer — impossible to bypass, even if the developer tries to call models directly with their bearer token.

**How it works:**
- When provisioning a key, the platform attaches a custom inline policy to the IAM user that only allows the models approved for that cost centre
- When a CCO or Admin changes allowed models, the platform updates the IAM policy on all affected users
- When a global model restriction changes (Admin removes a model), the platform removes it from all IAM policies immediately
- `AmazonBedrockLimitedAccess` is replaced with a scoped custom policy

**Example policy (Sonnet + Haiku only, with inference profile support):**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowModelInvocation",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-*",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-*",
        "arn:aws:bedrock:*:*:application-inference-profile/*"
      ]
    },
    {
      "Sid": "AllowInferenceProfileResolution",
      "Effect": "Allow",
      "Action": ["bedrock:GetInferenceProfile", "bedrock:ListInferenceProfiles"],
      "Resource": [
        "arn:aws:bedrock:*:*:inference-profile/*",
        "arn:aws:bedrock:*:*:application-inference-profile/*"
      ]
    },
    {
      "Sid": "AllowBearerTokenUsage",
      "Effect": "Allow",
      "Action": "bedrock:CallWithBearerToken",
      "Resource": "*"
    }
  ]
}
```

**Notes on the policy:**
- `bedrock:CallWithBearerToken` is a confirmed IAM action that controls bearer token usage. The `bedrock:bearerTokenType` condition key can filter by `SHORT_TERM` or `LONG_TERM`.
- `bedrock:GetInferenceProfile` lets Claude Code resolve an inference profile ARN to its backing model (used to select the correct request shape). Without it, Claude Code retries with the alternate shape — requests still succeed but add an extra round-trip.
- `application-inference-profile/*` resources are required because Claude Code invokes models through inference profiles when `modelOverrides` are configured (Decision #2).

**Why not alternatives:**
- Application Inference Profiles bind to a single model — if a CCO allows 2 models, you'd need 2 profiles per key. IAM policy handles multiple models cleanly in a single statement.
- App-level enforcement is weak — developer could bypass it with the bearer token directly.
- Guardrails are for content filtering, not model access control.

**See:** [research/02](../research/02-aws-iam-access-control.md), [research/09](../research/09-bedrock-api-keys-deep-dive.md)

---

## 4. Technology Stack ✅ DECIDED

### 4a. Backend: Python + FastAPI
- Clean async support; excellent for polling CloudWatch and calling IAM APIs
- `boto3` is the best AWS SDK available (native Python)
- Pydantic for request/response validation
- SQLAlchemy + Alembic for DB ORM and migrations
- Background tasks / scheduler (e.g., APScheduler or FastAPI background tasks) for the CloudWatch polling loop

### 4b. Frontend: React + Vite
- TypeScript for type safety
- Component library TBD (e.g., Ant Design, shadcn/ui, or MUI) — decide during implementation
- React Router for navigation
- React Query (TanStack Query) for API data fetching and caching

### 4c. Database: PostgreSQL
- Relational data (users, keys, cost centres, approvals) maps naturally
- JSONB columns for flexible fields (e.g., policy documents, audit metadata)
- Good audit log support
- Hosted via Docker Compose locally; RDS/Aurora for production

### 4d. Deployment
- **Local / PoC:** Docker Compose — spins up backend, frontend, and PostgreSQL together
- **Production:** Docker on ECS (or EC2) — same containers, different orchestration

### Docker Compose structure (local dev):
```
services:
  backend:    # Python + FastAPI (port 8000)
  frontend:   # React + Vite (port 5173, proxies API to backend)
  db:          # PostgreSQL (port 5432)
```

---

## 5. Key-to-Developer Attribution ✅ DECIDED

**Decision: Automatic — one IAM user per key (inherent to Bedrock API Keys)**

This decision is resolved by Decision #1. Each long-term Bedrock API Key creates a unique IAM user. Every Bedrock API call is logged in CloudTrail with that IAM user identity. Attribution is automatic — no additional work needed.

**How it works:**
- Platform creates IAM user with naming convention: `claude-{developer}-{costcentre}` (e.g., `claude-john-cc1234`)
- IAM user is tagged: `Developer=john`, `CostCentre=CC-1234`, `ManagedBy=claude-aws-manager`
- CloudTrail logs every `InvokeModel` call with this IAM user identity
- Invocation logs (S3/CloudWatch) include the IAM user identity per request
- No custom headers needed — Claude Code is unaware of the attribution mechanism

---

## 6. Budget Enforcement Timing ✅ DECIDED

**Decision: Poll CloudWatch every 5 minutes (aligned with Decision #2)**

The cost tracking polling loop (Decision #2) doubles as budget enforcement. Each poll cycle:
1. Fetch token counts from CloudWatch per inference profile (CC-level)
2. Calculate cost using cached pricing rates (tokens × per-model price)
3. Compare against CC rolling budget and per-key rolling limits
4. If CC budget exceeded → disable all keys in that CC via `UpdateServiceSpecificCredential(Status=Inactive)`
5. If per-key limit exceeded → disable that specific key
6. Send alerts at configurable thresholds (50%, 80%, 100%)

**Accepted trade-off:** A developer could overshoot the budget by up to ~5 minutes of usage before enforcement kicks in. Worst case with N active developers in a CC is ~5 minutes × N developers. Acceptable for PoC; can tighten polling for CCs near their budget threshold in production.

**Remaining sub-decision:**
- Should we pre-calculate "estimated remaining budget" for the developer dashboard? (Nice-to-have, can defer to production)

---

## 7. Notification Infrastructure ✅ DECIDED

**Decision: Deferred to production.** No email or Slack notifications in the PoC. All status changes are visible in the web UI.

When implemented in production:
- Email via AWS SES (verified domain)
- Slack via Incoming Webhooks (simplest)
- Notification types: key approved/rejected, budget threshold alerts, key expiry reminders

---

## 8. PoC Scope vs Production Scope ✅ DECIDED

**PoC scope (must-have):**
- [ ] Hard-coded auth (no SSO)
- [ ] Key request → approval → provisioning flow (**real AWS — actually provisions Bedrock API Keys**)
- [ ] Basic developer dashboard (view keys, status, setup instructions)
- [ ] CCO approval screen with constraint setting
- [ ] Admin cost centre management
- [ ] Usage charts and visualisations
- [ ] Budget alerts with configurable thresholds
- [ ] Key revocation

**Deferred to production:**
- [ ] Corporate SSO (OIDC/SAML)
- [ ] Email and Slack notifications (#7)
- [ ] CSV export
- [ ] Guardrails / content filtering
- [ ] SSO-based auto-offboarding
- [ ] Drift reconciliation
- [ ] Unusual usage spike detection

**PoC provisions real AWS credentials** — the value of the PoC is proving the end-to-end flow works, from key request through to a developer actually using Claude Code with the provisioned token.

---

## 9. AWS Account Strategy ✅ DECIDED

**Decision: Dedicated AWS account for Claude Code Bedrock usage.**

Clean cost separation, simpler IAM (no policy conflicts with other workloads), isolated blast radius. Anthropic docs also recommend this approach.

---

## 10. Key Storage & Security ✅ DECIDED

**Decision: Don't store the bearer token. Display once on creation/regeneration. Developer regenerates if lost.**

Requirement updated: keys are no longer "retrievable" — instead developers can **regenerate** (via `ResetServiceSpecificCredential`), which issues a new bearer token and invalidates the old one.

**What we store in our DB (all non-sensitive):**
- `ServiceSpecificCredentialId` — for management operations (deactivate/reset/delete)
- IAM username — for policy updates and cleanup
- Key metadata — status, expiry, cost centre, developer, creation date

**What we DON'T store:**
- The bearer token itself — shown once, never persisted

**Security benefit:** No encrypted secrets in the database at all. Eliminates master key management, KMS costs, encryption-at-rest concerns, and the entire class of "stolen DB = stolen credentials" attacks.

**Regeneration flow:**
```
Developer clicks "Regenerate" → ResetServiceSpecificCredential → new token displayed once → old token invalidated immediately
```

---

## 11. Real AWS vs Mock for Development ✅ DECIDED

**Decision: Hybrid — mock/stub layer by default, real AWS for integration testing.**

Since the PoC provisions real AWS credentials (#8), the app needs a real AWS integration path. But day-to-day development uses a mock/stub AWS layer for speed. Integration tests run against the dedicated AWS account (#9) to validate real behaviour.

- **Local dev (default):** Mock AWS layer — fast, no AWS costs, works offline
- **Integration tests:** Real AWS (dedicated dev account) — validates actual IAM/Bedrock/CloudWatch behaviour
- **PoC demo:** Real AWS — end-to-end proof

---

## Decision Status

| # | Decision | Status |
|---|----------|--------|
| 1 | Credential Strategy | ✅ **Bedrock API Keys (long-term)** |
| 2 | Cost Tracking | ✅ **CloudWatch Metrics per inference profile + AWS Price List API** |
| 3 | Model Restrictions | ✅ **IAM Policy on underlying user** |
| 4 | Technology Stack | ✅ **Python+FastAPI / React+Vite / PostgreSQL / Docker Compose** |
| 5 | Key-to-Developer Attribution | ✅ **Automatic via IAM user per key** |
| 6 | Budget Enforcement Timing | ✅ **Poll every 1-2 min (same loop as #2)** |
| 7 | Notification Infrastructure | ✅ **Deferred to production** |
| 8 | PoC Scope | ✅ **Defined — real AWS, includes charts + budget alerts** |
| 9 | AWS Account Strategy | ✅ **Dedicated AWS account** |
| 10 | Key Storage & Security | ✅ **Don't store token — display once, regenerate if lost** |
| 11 | Real AWS vs Mock | ✅ **Hybrid — mock default, real AWS for integration** |

