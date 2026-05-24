# AWS Bedrock — IAM & Access Control for Key Management

## Overview

This document covers how to use AWS IAM to programmatically manage access to Bedrock models — the core mechanism our platform will use to provision and restrict developer keys.

**Sources:**
- https://docs.aws.amazon.com/bedrock/latest/userguide/security-iam.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html

---

## IAM Policy for Claude Code Users

The minimum IAM policy a developer needs to use Claude Code with Bedrock:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowModelAndInferenceProfileAccess",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:ListInferenceProfiles",
        "bedrock:GetInferenceProfile"
      ],
      "Resource": [
        "arn:aws:bedrock:*:*:inference-profile/*",
        "arn:aws:bedrock:*:*:application-inference-profile/*",
        "arn:aws:bedrock:*:*:foundation-model/*"
      ]
    },
    {
      "Sid": "AllowMarketplaceSubscription",
      "Effect": "Allow",
      "Action": [
        "aws-marketplace:ViewSubscriptions",
        "aws-marketplace:Subscribe"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:CalledViaLast": "bedrock.amazonaws.com"
        }
      }
    }
  ]
}
```

---

## Model-Level Access Restriction

### Allow Only Specific Models

Restrict a user to only use specific Claude models (e.g., Sonnet only, no Opus):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"
      ]
    }
  ]
}
```

### Deny Specific Models

Block access to a model after it's already been granted:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Deny",
      "Action": ["bedrock:*"],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-4-20250918-v1:0"
      ]
    }
  ]
}
```

---

## Credential Strategies for Our Platform

### Option 1: IAM Users with Access Keys

**Approach:** Create an IAM user per developer, attach model-restricted policies, generate access keys.

**Pros:**
- Full IAM policy control per user
- Can restrict models at the IAM level
- Easy to revoke (delete access key or disable user)
- CloudTrail logs per IAM user for audit

**Cons:**
- Long-lived credentials (security risk if leaked)
- IAM user limit per account (5,000 default)
- More complex lifecycle management

**Provisioning:**
```bash
# Create user
aws iam create-user --user-name claude-dev-john

# Attach policy
aws iam attach-user-policy --user-name claude-dev-john --policy-arn arn:aws:iam::123456789012:policy/ClaudeCodeSonnetOnly

# Create access key
aws iam create-access-key --user-name claude-dev-john
```

**Revocation:**
```bash
# Disable specific access key
aws iam update-access-key --user-name claude-dev-john --access-key-id AKIA... --status Inactive

# Or delete entirely
aws iam delete-access-key --user-name claude-dev-john --access-key-id AKIA...
```

### Option 2: IAM Roles with Temporary Credentials (STS)

**Approach:** Create roles per cost centre with model restrictions. Use `sts:AssumeRole` to generate temporary credentials.

**Pros:**
- Temporary credentials (auto-expire)
- Fewer IAM users to manage
- Can set session duration (1 hour to 12 hours)
- Better security posture

**Cons:**
- Credentials expire — developers need to refresh
- More complex for developer experience
- Need a mechanism to assume roles (could be app-mediated)

**Provisioning:**
```bash
# Create role with trust policy
aws iam create-role --role-name claude-cc1234-developer \
  --assume-role-policy-document file://trust-policy.json

# Assume role to get temporary credentials
aws sts assume-role \
  --role-arn arn:aws:iam::123456789012:role/claude-cc1234-developer \
  --role-session-name john-session \
  --duration-seconds 43200
```

### Option 3: Bedrock API Keys (Recommended for Simplicity)

**Approach:** Use Bedrock's native API key feature. Simpler than full IAM credential management.

**Pros:**
- Simple single token for developers
- No AWS CLI configuration needed
- Easy to manage via API
- Purpose-built for Bedrock access

**Cons:**
- Newer feature — less documentation
- May have fewer fine-grained IAM controls
- Need to verify model-level restriction capabilities

**Usage:**
```bash
export AWS_BEARER_TOKEN_BEDROCK=your-bedrock-api-key
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION=ap-southeast-2
```

---

## Tags for Cost Attribution

All IAM resources should be tagged for cost centre attribution:

```bash
aws iam tag-user --user-name claude-dev-john --tags \
  Key=CostCentre,Value=CC-1234 \
  Key=ManagedBy,Value=claude-aws-manager \
  Key=CreatedDate,Value=2026-05-23
```

---

## Service Control Policies (SCPs)

For organisation-wide restrictions, SCPs can enforce model access at the AWS Organizations level:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyUnauthorizedModels",
      "Effect": "Deny",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-*"
      ],
      "Condition": {
        "StringNotEquals": {
          "aws:PrincipalTag/AllowOpus": "true"
        }
      }
    }
  ]
}
```

---

## Key Lifecycle Management via IAM

| Action | IAM API Call |
|--------|-------------|
| Create key | `iam:CreateAccessKey` |
| Disable key | `iam:UpdateAccessKey` (Status=Inactive) |
| Delete key | `iam:DeleteAccessKey` |
| List keys | `iam:ListAccessKeys` |
| Check last used | `iam:GetAccessKeyLastUsed` |
| Delete user | `iam:DeleteUser` |

---

## IAM Limits to Consider

| Resource | Default Limit |
|----------|--------------|
| IAM users per account | 5,000 |
| Access keys per user | 2 |
| Policies per user | 10 (direct) |
| Managed policies per account | 1,500 |
| Policy size | 6,144 characters |
| Groups per account | 300 |

For ~300 developers, we are well within limits.

---

## Recommendations for Our Platform

1. **Use IAM Users + Access Keys** for the PoC — simplest to implement, full control
2. **Investigate Bedrock API Keys** as a potentially simpler alternative
3. **Application Inference Profiles** for cost tracking per cost centre
4. **Tag everything** with cost centre, developer, and creation date
5. **Use IAM policies** for model restrictions (Allow only Sonnet, deny Opus, etc.)
6. **Create a dedicated AWS account** for Claude Code to simplify cost tracking

---

## References

- https://docs.aws.amazon.com/bedrock/latest/userguide/security-iam.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_service-with-iam.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_id-based-policy-examples.html
- https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html
- https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html
