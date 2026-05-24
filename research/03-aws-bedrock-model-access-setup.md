# AWS Bedrock — Model Access & Initial Setup

## Overview

Before the platform can provision keys, the AWS account must have Bedrock model access enabled. This is a one-time setup per AWS account.

**Source:** https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html

---

## One-Time Account Setup

### Step 1: Enable Model Access (Automatic)

Access to all Amazon Bedrock foundation models is **enabled by default** with the correct AWS Marketplace permissions. Simply invoke the model or use the console.

### Step 2: Anthropic Use Case Form (Required Once)

For Anthropic models specifically, you must submit use case details **once per AWS account** (or once at the organization's management account).

**Required Information:**
- Company name (max 128 chars)
- Company website (max 128 chars)
- Intended users: 0=Internal, 1=External, 2=Internal_and_External
- Industry option (max 128 chars)
- Use cases description (max 8,192 chars)

**Via CLI:**
```bash
aws bedrock put-use-case-for-model-access \
  --form-data <Base64EncodedFormData>
```

**Form data JSON (before base64 encoding):**
```json
{
  "companyName": "Your Company",
  "companyWebsite": "https://yourcompany.com",
  "intendedUsers": 0,
  "industryOption": "Technology",
  "otherIndustryOption": "",
  "useCases": "Internal developer tooling using Claude Code for software development"
}
```

> Access is granted **immediately** after use case details are submitted.
> Submission at the root account is inherited by other accounts in the same AWS Organization.

### Step 3: AWS Marketplace Permissions

The IAM role used must have:
- `aws-marketplace:Subscribe`
- `aws-marketplace:Unsubscribe`
- `aws-marketplace:ViewSubscriptions`

---

## Programmatic Model Access Management

### List Available Model Agreements

```bash
aws bedrock list-foundation-model-agreement-offers --model-id anthropic.claude-sonnet-4-20250514-v1:0
```

### Create Model Agreement (Grant Access)

```bash
aws bedrock create-foundation-model-agreement \
  --model-id anthropic.claude-sonnet-4-20250514-v1:0 \
  --offer-token <OfferToken>
```

### Check Model Availability

```bash
aws bedrock get-foundation-model-availability --model-id anthropic.claude-sonnet-4-20250514-v1:0
```

**Response:**
```json
{
  "modelId": "anthropic.claude-sonnet-4-20250514-v1:0",
  "agreementAvailability": {
    "status": "AVAILABLE"
  },
  "authorizationStatus": "AUTHORIZED",
  "entitlementAvailability": "AVAILABLE",
  "regionAvailability": "AVAILABLE"
}
```

### Delete Model Agreement (Revoke Access)

```bash
aws bedrock delete-foundation-model-agreement --model-id <ModelId>
```

> **Important:** Deleting model access is not enough to block future access since invoking the model will re-create access. Apply restrictive Deny IAM policies to truly block.

---

## Available Claude Models on Bedrock

| Model | Model ID | Notes |
|-------|----------|-------|
| Claude Opus 4.7 | `anthropic.claude-opus-4-7` | Latest, most capable |
| Claude Opus 4.6 | `anthropic.claude-opus-4-6` | Previous Opus version |
| Claude Sonnet 4.6 | `anthropic.claude-sonnet-4-6` | Good balance of capability/cost |
| Claude Haiku 4.5 | `anthropic.claude-haiku-4-5-20251001-v1:0` | Fast, low cost |

### Cross-Region Inference Profile IDs

These use a region prefix (e.g., `us.`) and route across multiple regions:
- `us.anthropic.claude-opus-4-7`
- `us.anthropic.claude-sonnet-4-6`
- `us.anthropic.claude-haiku-4-5-20251001-v1:0`

---

## Inference Profiles (Key for Cost Tracking)

Inference profiles are a critical mechanism for our platform. They allow:

1. **Cost tracking per user/team** — create an application inference profile per cost centre
2. **Cross-region routing** — increase throughput by routing across regions
3. **CloudWatch metrics** — track usage per inference profile

### Create an Application Inference Profile

```bash
aws bedrock create-inference-profile \
  --inference-profile-name "CC-1234-profile" \
  --model-source '{"copyFrom": "arn:aws:bedrock:ap-southeast-2::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0"}' \
  --tags Key=CostCentre,Value=CC-1234
```

**Response returns:** `inferenceProfileArn` — this ARN is used in place of model IDs for invocations.

### Use Profile for Invocation

Developers use the inference profile ARN instead of the model ID:
```bash
export ANTHROPIC_MODEL='arn:aws:bedrock:ap-southeast-2:123456789012:application-inference-profile/your-profile-id'
```

### Cost Allocation with Tags

Tags on inference profiles can be activated as cost allocation tags in AWS Billing:
- Tag: `CostCentre=CC-1234`
- Tag: `Developer=john.doe`
- Tag: `Team=Engineering`

---

## Region Availability

Our target region is **ap-southeast-2 (Sydney, Australia)**.

### Check Available Models in Region

```bash
aws bedrock list-inference-profiles --region ap-southeast-2
```

### Cross-Region Inference

If models aren't available in ap-southeast-2, cross-region inference profiles can route to other regions:

```bash
aws bedrock list-inference-profiles --region ap-southeast-2 --type-equals SYSTEM_DEFINED
```

---

## Quotas & Limits

| Quota | Default |
|-------|---------|
| Tokens per minute (TPM) | Model-dependent |
| Tokens per day (TPD) | TPM × 24 × 60 |
| Requests per minute (RPM) | Model-dependent |

### Token Burndown Rate (Claude 3.7+)

- Output tokens consume 5× from quota (1 output token = 5 quota tokens)
- Input tokens are 1:1
- You're only **billed** for actual tokens, not the quota consumption

### Requesting Quota Increases

```bash
aws service-quotas request-service-quota-increase \
  --service-code bedrock \
  --quota-code <quota-code> \
  --desired-value <value>
```

---

## Relevance to Our Platform

| Requirement | Bedrock Feature |
|------------|----------------|
| Per-cost-centre cost tracking | Application Inference Profiles with CostCentre tags |
| Model restrictions | IAM Resource ARN filtering on foundation-model/ |
| Usage monitoring | CloudWatch metrics per inference profile |
| Budget enforcement | CloudWatch alarms + Lambda to disable keys |
| Audit trail | CloudTrail + Model invocation logging |
| Region (Australia) | ap-southeast-2 or cross-region profiles |

---

## References

- https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-create.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-token-burndown.html
- https://docs.aws.amazon.com/general/latest/gr/bedrock.html
