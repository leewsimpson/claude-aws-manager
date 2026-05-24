# Bedrock API Keys — Deep Dive

## Overview

Bedrock API Keys are a **wrapper around IAM users** that provide a simpler bearer-token credential. This is a critical finding for our platform — they give us simple developer UX with full IAM control underneath.

**Sources:**
- https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-reference.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-how.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-generate.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-permissions.html
- https://aws.amazon.com/blogs/machine-learning/accelerate-ai-development-with-amazon-bedrock-api-keys/

---

## How Long-Term API Keys Actually Work

When you create a long-term Bedrock API key, **Bedrock automatically creates an IAM user** and associates the key with it. The key:

1. Is a **service-specific credential** (type: `iam:CreateServiceSpecificCredential`)
2. Is backed by a real IAM user with attached policies
3. Has configurable expiration (1 day to no expiration)
4. Has the `AmazonBedrockLimitedAccess` managed policy attached by default
5. **Can only be used with Bedrock** — not with other AWS services
6. Uses bearer token auth (`Authorization: Bearer <key>`)

This means: **Bedrock API Keys ARE IAM users underneath, but with a simpler token format.**

### Short-Term Keys (Not Useful for Us)

- Last up to 12 hours (or session duration, whichever is shorter)
- Inherit permissions from the IAM principal that generates them
- No underlying IAM user created
- For us: not useful — developers need long-lived keys

---

## Programmatic Key Creation (via CLI/SDK)

This is exactly what our platform would do:

```bash
# Step 1: Create an IAM user
aws iam create-user --user-name bedrock-api-user-dev1-cc1234

# Step 2: Attach base policy
aws iam attach-user-policy \
  --user-name bedrock-api-user-dev1-cc1234 \
  --policy-arn arn:aws:iam::aws:policy/AmazonBedrockLimitedAccess

# Step 3: (Optional) Attach model restriction policy
aws iam put-user-policy \
  --user-name bedrock-api-user-dev1-cc1234 \
  --policy-name SonnetOnlyAccess \
  --policy-document file://sonnet-only-policy.json

# Step 4: Generate the Bedrock API key with expiration
aws iam create-service-specific-credential \
  --user-name bedrock-api-user-dev1-cc1234 \
  --service-name bedrock.amazonaws.com \
  --credential-age-days 90
```

**Response includes:**
- `ServiceApiKeyValue` — **this is the bearer token** the developer uses
- `ServiceSpecificCredentialId` — used for management operations (deactivate, reset, delete)

---

## Model Restrictions: YES, Fully Supported

Since the API key is backed by an IAM user, you **can modify the IAM user's policies** to restrict models. From the docs:

> "you can modify permissions as needed through the IAM service"

### Example: Allow Sonnet and Haiku Only

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowSonnetAndHaikuOnly",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-*",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-*"
      ]
    },
    {
      "Sid": "AllowBedrockAPIKeyUsage",
      "Effect": "Allow",
      "Action": "bedrock:CallWithBearerToken",
      "Resource": "*"
    }
  ]
}
```

**Conclusion: Model restriction per key is fully supported via IAM policies on the underlying user.**

---

## Revocation: YES, Multiple Options

| Action | Method | API Call |
|--------|--------|----------|
| **Deactivate** (reversible) | Console or API | `UpdateServiceSpecificCredential` with `Status=Inactive` |
| **Reset** (new key value) | Console or API | `ResetServiceSpecificCredential` |
| **Delete** (permanent) | Console or API | `DeleteServiceSpecificCredential` |

### Programmatic Revocation

```bash
# Deactivate (key stops working immediately, can be reactivated)
aws iam update-service-specific-credential \
  --user-name bedrock-api-user-dev1-cc1234 \
  --service-specific-credential-id ABCDE12345 \
  --status Inactive

# Delete permanently
aws iam delete-service-specific-credential \
  --user-name bedrock-api-user-dev1-cc1234 \
  --service-specific-credential-id ABCDE12345
```

**Conclusion: Revocation is fully supported — deactivate for soft stop, delete for permanent.**

---

## Per-Key Cost Tracking: YES, via IAM User Identity

Since each long-term API key creates a unique IAM user:

1. **CloudTrail** logs every API call with the IAM user identity
2. **CloudWatch metrics** can be filtered by IAM user
3. **Model invocation logging** captures the IAM user on every request
4. **Application Inference Profiles** can be combined (profile per cost centre + IAM user identity = per-key tracking within a cost centre)

### Approach: Invocation Logs for Per-Key Attribution

Each Bedrock invocation log includes the `accountId` and the calling identity. With one IAM user per key, we get per-key attribution in the logs automatically.

### Approach: Inference Profile Per Cost Centre

Create an inference profile per cost centre and configure the developer's key to use it. CloudWatch metrics are then scoped per cost centre via the profile, and per-key within the cost centre via the IAM user identity in the invocation logs.

**Conclusion: Per-key cost tracking is supported via the IAM user identity in CloudTrail/invocation logs.**

---

## Expiration: Built-In

```bash
aws iam create-service-specific-credential \
  --user-name bedrock-api-user \
  --service-name bedrock.amazonaws.com \
  --credential-age-days 90  # Key expires after 90 days
```

You can also enforce max expiration via SCP:

```json
{
  "Effect": "Deny",
  "Action": "iam:CreateServiceSpecificCredential",
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "iam:ServiceSpecificCredentialServiceName": "bedrock.amazonaws.com"
    },
    "NumericGreaterThanEquals": {
      "iam:ServiceSpecificCredentialAgeDays": "90"
    }
  }
}
```

**Conclusion: Expiration is a first-class feature of Bedrock API Keys.**

---

## Audit & Compliance

- All API calls logged in **CloudTrail** (the IAM user identity is recorded)
- The API key itself is passed as an `Authorization` header and is **NOT logged** (security)
- SCP policies can control who can generate and use keys

---

## Limitations

1. **Bedrock-only** — Keys cannot be used with other AWS services (but that's fine for us)
2. **AWS recommends short-term for production** — Long-term keys are labelled "for exploration." However, the underlying mechanism (IAM user + service-specific credential) is a standard IAM pattern. The warning is about security best practices, not a technical limitation.
3. **Console generation** — The console UI only generates keys for the current user. Programmatic creation via `CreateServiceSpecificCredential` is needed for our use case.
4. **Not supported for**: `InvokeModelWithBidirectionalStream`, Agents for Bedrock, Data Automation for Bedrock

---

## What Our Platform Would Do

```
1. CCO approves key request for developer "john" on cost centre "CC-1234"
     │
2. Platform creates IAM user: "claude-john-cc1234"
   - Tags: CostCentre=CC-1234, Developer=john, ManagedBy=claude-aws-manager
     │
3. Platform attaches IAM policies:
   - AmazonBedrockLimitedAccess (base)
   - Custom policy restricting to allowed models (e.g., Sonnet only)
   - bedrock:CallWithBearerToken (allow API key usage)
     │
4. Platform calls CreateServiceSpecificCredential:
   - service-name: bedrock.amazonaws.com
   - credential-age-days: 90 (from CCO's expiry setting)
     │
5. Platform stores:
   - ServiceSpecificCredentialId (for management)
   - ServiceApiKeyValue (encrypted, for developer retrieval)
     │
6. Developer receives single token:
   export AWS_BEARER_TOKEN_BEDROCK="br-xxxxxxxx"
   export CLAUDE_CODE_USE_BEDROCK=1
   export AWS_REGION=ap-southeast-2
   claude
     │
7. To revoke: Platform calls UpdateServiceSpecificCredential(Status=Inactive)
8. To delete: Platform calls DeleteServiceSpecificCredential + DeleteUser
```

---

## Verdict

**Bedrock API Keys are the right credential strategy for our platform.**

They provide:
- ✅ Simple developer experience (single bearer token)
- ✅ Model restrictions (via IAM policies on underlying user)
- ✅ Per-key cost tracking (via IAM user identity in CloudTrail/invocation logs)
- ✅ Revocation (deactivate/reset/delete via API)
- ✅ Configurable expiration (built-in)
- ✅ Programmatic creation (via IAM `CreateServiceSpecificCredential`)
- ✅ Audit trail (CloudTrail per IAM user)
- ✅ Bedrock-scoped only (can't be used for other AWS services)
- ✅ CloudTrail won't log the key value itself (security)

---

## References

- https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-reference.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-how.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-generate.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-permissions.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-revoke.html
- https://docs.aws.amazon.com/IAM/latest/APIReference/API_CreateServiceSpecificCredential.html
- https://aws.amazon.com/blogs/machine-learning/accelerate-ai-development-with-amazon-bedrock-api-keys/
