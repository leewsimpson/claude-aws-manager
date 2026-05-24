# Architecture & Implementation Considerations

## Overview

This document summarises key architectural decisions informed by the research, covering how AWS services map to our platform requirements.

---

## High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                        Our Platform                                  │
├────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────┐   ┌──────────────┐   ┌───────────────┐              │
│  │  Web UI  │   │  REST API    │   │  Background   │              │
│  │ (React)  │   │  (Express/   │   │  Workers      │              │
│  │          │   │   FastAPI)   │   │  (Scheduler)  │              │
│  └────┬─────┘   └──────┬───────┘   └───────┬───────┘              │
│       │                 │                    │                       │
│       └────────────┬────┘                    │                       │
│                    ▼                         │                       │
│           ┌────────────────┐                 │                       │
│           │   Database     │                 │                       │
│           │ (PostgreSQL)   │                 │                       │
│           └────────────────┘                 │                       │
│                                              │                       │
└──────────────────────────────────────────────┼───────────────────────┘
                                               │
                    ┌──────────────────────────┘
                    ▼
┌────────────────────────────────────────────────────────────────────┐
│                        AWS Services                                  │
├────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐    │
│  │    IAM      │  │  Bedrock    │  │   CloudWatch            │    │
│  │             │  │             │  │                         │    │
│  │ - Users     │  │ - Models    │  │ - Metrics               │    │
│  │ - Policies  │  │ - Profiles  │  │ - Alarms                │    │
│  │ - Keys      │  │ - Guardrails│  │ - Logs                  │    │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘    │
│                                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐    │
│  │   STS       │  │    S3       │  │   Cost Explorer         │    │
│  │             │  │             │  │                         │    │
│  │ - AssumeRole│  │ - Logs      │  │ - Cost reports          │    │
│  │ - Temp creds│  │ - Exports   │  │ - Tag-based filtering   │    │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘    │
│                                                                      │
│  ┌─────────────┐  ┌─────────────┐                                  │
│  │  Cognito    │  │    SNS      │                                  │
│  │             │  │             │                                  │
│  │ - Auth      │  │ - Alerts    │                                  │
│  │ - SSO       │  │ - Notifications│                               │
│  └─────────────┘  └─────────────┘                                  │
│                                                                      │
└────────────────────────────────────────────────────────────────────┘
```

---

## Key Provisioning Flow (Detailed)

When a key request is approved:

```
1. CCO approves request in UI
        │
2. API creates IAM User (or generates Bedrock API Key)
   - Username: claude-{developer-id}-{cost-centre-id}
   - Tags: CostCentre, Developer, CreatedDate, Expiry
        │
3. Attach IAM Policy
   - Allow: bedrock:InvokeModel, bedrock:InvokeModelWithResponseStream
   - Resource: Only allowed model ARNs
   - Optional: Restrict to specific inference profile
        │
4. Create Access Key for IAM User
   - Store encrypted in our database
   - Record key ID for lifecycle management
        │
5. Create/Assign Application Inference Profile
   - Profile per cost centre (or per developer)
   - Tags for cost tracking
        │
6. Notify developer
   - Email/Slack notification
   - Key visible in portal with setup instructions
        │
7. Record in audit log
   - Who approved, when, what constraints
```

**Target completion time:** < 10 seconds

---

## Key Revocation Flow

```
1. Revocation triggered (admin, CCO, developer, or system)
        │
2. Disable IAM Access Key
   aws iam update-access-key --status Inactive
        │
3. Update database record
   - Status: Revoked
   - RevokedBy, RevokedDate, Reason
        │
4. (Optional) Delete IAM User after grace period
   - Clean up policies, keys, user
        │
5. Notify developer
   - "Your key for CC-1234 has been revoked"
        │
6. Record in audit log
```

---

## Cost Tracking Data Pipeline

```
┌───────────────────────────────────────────────────────────┐
│ Every 5 minutes (Background Worker)                        │
├───────────────────────────────────────────────────────────┤
│                                                            │
│  1. Query CloudWatch for token metrics                     │
│     - Per inference profile (per cost centre)              │
│     - InputTokenCount, OutputTokenCount                    │
│                                                            │
│  2. Calculate costs                                        │
│     - Multiply tokens by model pricing                     │
│     - Aggregate per key, per cost centre                   │
│                                                            │
│  3. Check budgets                                          │
│     - Rolling period: sum costs over N-day window          │
│     - Lifetime budget: sum all costs for key               │
│     - Cost centre cap: sum all keys in cost centre         │
│                                                            │
│  4. Enforce limits                                         │
│     - If limit hit → disable key (iam:UpdateAccessKey)     │
│     - If rolling period limit → check daily for re-enable  │
│     - If cost centre cap → disable ALL keys in CC          │
│                                                            │
│  5. Send alerts                                            │
│     - 50% threshold → email/Slack warning                  │
│     - 80% threshold → email/Slack urgent                   │
│     - 100% → key disabled + notification                   │
│                                                            │
└───────────────────────────────────────────────────────────┘
```

---

## Service Account Requirements

Our platform needs an IAM role/user with these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "IAMManagement",
      "Effect": "Allow",
      "Action": [
        "iam:CreateUser",
        "iam:DeleteUser",
        "iam:TagUser",
        "iam:UntagUser",
        "iam:CreateAccessKey",
        "iam:DeleteAccessKey",
        "iam:UpdateAccessKey",
        "iam:ListAccessKeys",
        "iam:GetAccessKeyLastUsed",
        "iam:AttachUserPolicy",
        "iam:DetachUserPolicy",
        "iam:CreatePolicy",
        "iam:DeletePolicy",
        "iam:ListUsers",
        "iam:GetUser"
      ],
      "Resource": "arn:aws:iam::*:user/claude-*"
    },
    {
      "Sid": "BedrockManagement",
      "Effect": "Allow",
      "Action": [
        "bedrock:CreateInferenceProfile",
        "bedrock:DeleteInferenceProfile",
        "bedrock:GetInferenceProfile",
        "bedrock:ListInferenceProfiles",
        "bedrock:TagResource",
        "bedrock:UntagResource",
        "bedrock:ListTagsForResource",
        "bedrock:GetFoundationModelAvailability",
        "bedrock:ListFoundationModels"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchRead",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics",
        "cloudwatch:PutMetricAlarm",
        "cloudwatch:DeleteAlarms"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CostExplorer",
      "Effect": "Allow",
      "Action": [
        "ce:GetCostAndUsage",
        "ce:GetCostForecast"
      ],
      "Resource": "*"
    },
    {
      "Sid": "Logging",
      "Effect": "Allow",
      "Action": [
        "logs:GetLogEvents",
        "logs:FilterLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:log-group:/aws/bedrock/*"
    }
  ]
}
```

---

## Database Schema (Key Tables)

```sql
-- Cost centres
CREATE TABLE cost_centres (
  id UUID PRIMARY KEY,
  code VARCHAR(50) UNIQUE NOT NULL,
  name VARCHAR(200) NOT NULL,
  budget_cap_dollars DECIMAL(10,2),
  status VARCHAR(20) DEFAULT 'active', -- active, archived
  created_at TIMESTAMP DEFAULT NOW()
);

-- Developer keys
CREATE TABLE developer_keys (
  id UUID PRIMARY KEY,
  developer_id UUID REFERENCES users(id),
  cost_centre_id UUID REFERENCES cost_centres(id),
  aws_username VARCHAR(100),
  aws_access_key_id VARCHAR(50),
  inference_profile_arn VARCHAR(300),
  status VARCHAR(20) DEFAULT 'pending', -- pending, active, stopped, expired, revoked
  allowed_models TEXT[], -- array of model IDs
  rolling_period_days INTEGER DEFAULT 7,
  rolling_period_limit_dollars DECIMAL(10,2),
  lifetime_budget_dollars DECIMAL(10,2),
  expires_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(developer_id, cost_centre_id) -- one key per CC per developer
);

-- Usage tracking
CREATE TABLE usage_records (
  id UUID PRIMARY KEY,
  key_id UUID REFERENCES developer_keys(id),
  recorded_at TIMESTAMP NOT NULL,
  input_tokens BIGINT DEFAULT 0,
  output_tokens BIGINT DEFAULT 0,
  model_id VARCHAR(200),
  cost_dollars DECIMAL(10,4)
);

-- Audit log
CREATE TABLE audit_log (
  id UUID PRIMARY KEY,
  action VARCHAR(50) NOT NULL,
  actor_id UUID REFERENCES users(id),
  target_type VARCHAR(50),
  target_id UUID,
  details JSONB,
  created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Technology Stack Considerations

### Backend Options

| Option | Pros | Cons |
|--------|------|------|
| Node.js + Express | Fast dev, good AWS SDK support | Callback hell if not careful |
| Python + FastAPI | Clean async, great AWS SDK (boto3) | Less common for web apps |
| .NET + ASP.NET Core | Enterprise-grade, strong typing | Heavier, slower iteration |

### Frontend Options

| Option | Pros | Cons |
|--------|------|------|
| React + Vite | Fast, huge ecosystem | Bundle size management |
| Next.js | SSR, API routes built-in | Overkill for SPA |
| Vue 3 | Simple, progressive | Smaller ecosystem |

### Database

- **PostgreSQL** — Robust, JSONB for flexible data, good for audit logs
- Hosted: AWS RDS or Aurora

### Notifications

- **Email:** AWS SES or SMTP
- **Slack:** Incoming webhooks or Slack API

---

## Dedicated AWS Account Recommendation

From the Claude Code Bedrock docs:
> "Create a dedicated AWS account for Claude Code to simplify cost tracking and access control."

Benefits:
- Clean cost separation
- Easier IAM management
- No interference with other workloads
- Simplified billing

---

## Key References (All Sources)

| Topic | URL |
|-------|-----|
| Claude Code Bedrock Setup | https://code.claude.com/docs/en/amazon-bedrock |
| Enterprise Deployment | https://code.claude.com/docs/en/third-party-integrations |
| Bedrock Model Access | https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html |
| Bedrock IAM | https://docs.aws.amazon.com/bedrock/latest/userguide/security-iam.html |
| Inference Profiles | https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles.html |
| Invocation Logging | https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html |
| Tagging | https://docs.aws.amazon.com/bedrock/latest/userguide/tagging.html |
| Cost Allocation Tags | https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/cost-alloc-tags.html |
| Bedrock Pricing | https://aws.amazon.com/bedrock/pricing/ |
| Token Quotas | https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-token-burndown.html |
| Guardrails | https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html |
| AWS Cognito SSO | https://docs.aws.amazon.com/cognito/latest/developerguide/what-is-amazon-cognito.html |
| Bedrock API Keys Blog | https://aws.amazon.com/blogs/machine-learning/accelerate-ai-development-with-amazon-bedrock-api-keys/ |
| Monitoring Guidance | https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock |
| Claude Code Quick Setup | https://community.aws/content/2tXkZKrZzlrlu0KfH8gST5Dkppq/claude-code-on-amazon-bedrock-quick-setup-guide |
