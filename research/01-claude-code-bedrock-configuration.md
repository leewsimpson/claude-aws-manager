# Claude Code — AWS Bedrock Configuration

## Overview

Claude Code can connect directly to AWS Bedrock. Developers configure credentials locally via environment variables. Once configured, Claude Code works immediately against the organisation's Bedrock instance.

**Source:** https://code.claude.com/docs/en/amazon-bedrock

---

## Prerequisites

- AWS account with Bedrock access enabled
- Access to desired Claude models (e.g., Claude Sonnet 4.6, Opus 4.6) in Bedrock
- AWS CLI installed and configured (optional if credentials are provided another way)
- Appropriate IAM permissions

---

## Core Environment Variables

```bash
# Enable Bedrock integration (REQUIRED)
export CLAUDE_CODE_USE_BEDROCK=1

# Set AWS region (REQUIRED — Claude Code does NOT read from .aws/config)
export AWS_REGION=us-east-1  # or ap-southeast-2 for Australia

# Optional: Override region for small/fast model
export ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION=us-west-2

# Optional: Override Bedrock endpoint URL for custom endpoints or gateways
export ANTHROPIC_BEDROCK_BASE_URL=https://bedrock-runtime.us-east-1.amazonaws.com
```

---

## Authentication Methods

Claude Code uses the **default AWS SDK credential chain**. Options include:

### Option A: AWS CLI Configuration
```bash
aws configure
```

### Option B: Environment Variables (Access Key)
```bash
export AWS_ACCESS_KEY_ID=your-access-key-id
export AWS_SECRET_ACCESS_KEY=your-secret-access-key
export AWS_SESSION_TOKEN=your-session-token  # if using temporary credentials
```

### Option C: SSO Profile
```bash
aws sso login --profile=<your-profile-name>
export AWS_PROFILE=your-profile-name
```

### Option D: AWS Management Console (`aws login`)
```bash
aws login
```

### Option E: Bedrock API Keys (Simplified, No Full AWS Credentials)
```bash
export AWS_BEARER_TOKEN_BEDROCK=your-bedrock-api-key
```

> Bedrock API keys provide a simpler authentication method without needing full AWS credentials.
> See: https://aws.amazon.com/blogs/machine-learning/accelerate-ai-development-with-amazon-bedrock-api-keys/

---

## Model Pinning (Important for Enterprise)

Pin specific model versions to avoid breakage when Anthropic releases updates. Without pinning, model aliases resolve to the latest version, which may not yet be enabled in the account.

```bash
export ANTHROPIC_DEFAULT_OPUS_MODEL='us.anthropic.claude-opus-4-7'
export ANTHROPIC_DEFAULT_SONNET_MODEL='us.anthropic.claude-sonnet-4-6'
export ANTHROPIC_DEFAULT_HAIKU_MODEL='us.anthropic.claude-haiku-4-5-20251001-v1:0'
```

These use **cross-region inference profile IDs** (with the `us.` prefix).

### Default Models (when no pinning set)

| Role | Default |
|------|---------|
| Primary model | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| Small/fast model | Same as primary model |

### Using Application Inference Profile ARNs

```bash
export ANTHROPIC_MODEL='arn:aws:bedrock:us-east-2:your-account-id:application-inference-profile/your-model-id'
```

### Model Overrides (Multiple Versions)

```json
{
  "modelOverrides": {
    "claude-opus-4-7": "arn:aws:bedrock:us-east-2:123456789012:application-inference-profile/opus-47-prod",
    "claude-opus-4-6": "arn:aws:bedrock:us-east-2:123456789012:application-inference-profile/opus-46-prod"
  }
}
```

---

## Advanced Credential Configuration (Enterprise SSO)

For AWS SSO and corporate identity providers, add these settings to the Claude Code settings file:

```json
{
  "awsAuthRefresh": "aws sso login --profile myprofile",
  "env": {
    "AWS_PROFILE": "myprofile"
  }
}
```

### `awsAuthRefresh`
- Runs only when credentials are expired (locally or when Bedrock returns credential error)
- Good for browser-based SSO flows

### `awsCredentialExport`
- Runs at session start AND on each credential reload
- Must output JSON:
```json
{
  "Credentials": {
    "AccessKeyId": "value",
    "SecretAccessKey": "value",
    "SessionToken": "value"
  }
}
```

---

## Service Tiers

```bash
export ANTHROPIC_BEDROCK_SERVICE_TIER=priority  # or default, flex
```

Options:
- `default` — Standard pricing/latency
- `flex` — Lower cost, potentially higher latency
- `priority` — Higher throughput, premium pricing

---

## AWS Guardrails Integration

Create a Guardrail in the Bedrock console, publish a version, then configure:

```json
{
  "env": {
    "ANTHROPIC_CUSTOM_HEADERS": "X-Amzn-Bedrock-GuardrailIdentifier: your-guardrail-id\nX-Amzn-Bedrock-GuardrailVersion: 1"
  }
}
```

---

## Proxy & Gateway Configuration

```bash
# Enable Bedrock
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION=us-east-1

# Corporate proxy
export HTTPS_PROXY='https://proxy.example.com:8080'

# LLM Gateway (custom routing)
export ANTHROPIC_BEDROCK_BASE_URL=https://your-gateway.example.com
```

---

## Key Notes for Our Project

1. **`AWS_REGION` is required** — Claude Code does not read from `.aws/config`
2. **`/login` and `/logout` are disabled** when using Bedrock (auth via AWS credentials)
3. **Bedrock API Keys** (`AWS_BEARER_TOKEN_BEDROCK`) are the simplest credential option — perfect for our use case of distributing keys to developers
4. **Application Inference Profiles** can be used for cost tracking per user/team
5. **1M token context window** is supported on Opus 4.7/4.6 and Sonnet 4.6

---

## Relevance to Our Requirements

| Requirement | Bedrock Capability |
|------------|-------------------|
| Credential distribution to developers | Bedrock API Keys or IAM user access keys |
| Model restrictions per key | IAM policy on `bedrock:InvokeModel` with Resource ARN filtering |
| Cost tracking per developer | Application Inference Profiles with tags |
| Region (ap-southeast-2) | Set via `AWS_REGION` environment variable |
| Key revocation | Delete IAM user/access key or revoke Bedrock API key |

---

## References

- https://code.claude.com/docs/en/amazon-bedrock
- https://code.claude.com/docs/en/third-party-integrations
- https://code.claude.com/docs/en/model-config
- https://code.claude.com/docs/en/env-vars
- https://code.claude.com/docs/en/settings
- https://aws.amazon.com/blogs/machine-learning/accelerate-ai-development-with-amazon-bedrock-api-keys/
