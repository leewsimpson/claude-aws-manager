# Developer Setup Instructions Template

## Overview

This documents what a developer's setup experience looks like when they receive a key from our platform. This is what the platform will display as "setup instructions" after key approval.

**Source:** https://code.claude.com/docs/en/amazon-bedrock

---

## Developer Experience: Getting Started with Claude Code

### What the Developer Receives from Our Platform

After their key request is approved, the developer gets:
1. **AWS Access Key ID** (or Bedrock API Key)
2. **AWS Secret Access Key** (if using IAM keys)
3. **AWS Region** (e.g., `ap-southeast-2`)
4. **Allowed models** (e.g., "Sonnet and Haiku only")
5. **Setup instructions** (copy-paste ready)

---

### Setup Instructions (Access Key Method)

```bash
# ===== Claude Code Setup — Cost Centre: CC-1234 =====
# Copy and paste these commands into your terminal

# 1. Set your credentials
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="wJalrX..."
export AWS_REGION="ap-southeast-2"

# 2. Enable Bedrock
export CLAUDE_CODE_USE_BEDROCK=1

# 3. (Optional) Pin model version for stability
export ANTHROPIC_DEFAULT_SONNET_MODEL='us.anthropic.claude-sonnet-4-6'

# 4. Start Claude Code
claude
```

### Setup Instructions (Bedrock API Key Method)

```bash
# ===== Claude Code Setup — Cost Centre: CC-1234 =====
# Copy and paste these commands into your terminal

# 1. Set your Bedrock API key
export AWS_BEARER_TOKEN_BEDROCK="br-..."
export AWS_REGION="ap-southeast-2"

# 2. Enable Bedrock
export CLAUDE_CODE_USE_BEDROCK=1

# 3. Start Claude Code
claude
```

---

### Persistent Configuration (Shell Profile)

For developers who want to persist their configuration:

```bash
# Add to ~/.bashrc or ~/.zshrc:
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION="ap-southeast-2"
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="wJalrX..."
```

### Configuration via Claude Code Settings File

Alternatively, developers can use the Claude Code settings file (no environment variable leakage to child processes):

**Location:** `~/.claude/settings.json` (or platform equivalent)

```json
{
  "env": {
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "AWS_REGION": "ap-southeast-2",
    "AWS_ACCESS_KEY_ID": "AKIA...",
    "AWS_SECRET_ACCESS_KEY": "wJalrX..."
  }
}
```

---

## Verification

Developers can verify their setup:

```bash
# Inside Claude Code, run:
/status
```

This shows:
- Provider: Amazon Bedrock
- Region: ap-southeast-2
- Available models
- Connection status

---

## Troubleshooting Guidance (for Platform Help Page)

| Issue | Solution |
|-------|----------|
| "Access Denied" | Check credentials are correct and not expired |
| "Model not available" | Model may not be enabled in the region; contact admin |
| "Region issues" | Ensure `AWS_REGION` is set (not just in `.aws/config`) |
| "On-demand throughput not supported" | Use inference profile ID instead of model ID |
| Key stopped working | Check if budget limit was reached; check portal for status |

---

## Platform UI: Key Display Page

When showing a key to the developer, the platform should display:

```
┌─────────────────────────────────────────────────────┐
│ Your Key for CC-1234 (Engineering)                   │
├─────────────────────────────────────────────────────┤
│ Status: ✅ Active                                    │
│ Models: Sonnet, Haiku                               │
│ Expires: 2026-08-21                                 │
│ Budget: $42.50 / $50.00 (7-day rolling)             │
│                                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Setup Instructions (click to copy)               │ │
│ │                                                  │ │
│ │ export CLAUDE_CODE_USE_BEDROCK=1                 │ │
│ │ export AWS_REGION="ap-southeast-2"              │ │
│ │ export AWS_ACCESS_KEY_ID="AKIA..."              │ │
│ │ export AWS_SECRET_ACCESS_KEY="wJalrX..."        │ │
│ │ claude                                          │ │
│ └─────────────────────────────────────────────────┘ │
│                                                      │
│ [Copy All] [Revoke Key]                             │
└─────────────────────────────────────────────────────┘
```

---

## References

- https://code.claude.com/docs/en/amazon-bedrock
- https://code.claude.com/docs/en/setup
- https://code.claude.com/docs/en/settings
- https://code.claude.com/docs/en/troubleshooting
