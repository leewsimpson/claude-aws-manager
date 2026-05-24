# AWS Bedrock Guardrails & Content Filtering

## Overview

AWS Bedrock Guardrails provide content filtering capabilities that can be applied per cost centre or globally — an optional/future requirement in our platform.

**Source:** https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html

---

## What Are Bedrock Guardrails?

Guardrails let you implement safeguards for generative AI applications:

- **Content filters** — Block harmful/inappropriate content
- **Denied topics** — Filter undesirable queries and responses
- **Sensitive information filters** — Redact PII
- **Word/phrase filters** — Block specific terms
- **Automated reasoning** — Validate outputs against rules

---

## Integration with Claude Code

Claude Code supports Guardrails via custom headers:

```json
{
  "env": {
    "ANTHROPIC_CUSTOM_HEADERS": "X-Amzn-Bedrock-GuardrailIdentifier: your-guardrail-id\nX-Amzn-Bedrock-GuardrailVersion: 1"
  }
}
```

### Per-Cost-Centre Guardrails

Each cost centre could have a different guardrail configuration:
- Engineering team: minimal filtering (code-focused)
- Marketing team: stricter content policies
- Finance team: PII redaction enabled

This would be implemented by:
1. Creating different Guardrails in Bedrock console
2. Setting the guardrail headers per developer's configuration

---

## Creating a Guardrail (Programmatic)

```bash
aws bedrock create-guardrail \
  --name "engineering-team-guardrail" \
  --description "Content filtering for engineering cost centres" \
  --content-policy-config '{
    "filtersConfig": [
      {"type": "SEXUAL", "inputStrength": "HIGH", "outputStrength": "HIGH"},
      {"type": "VIOLENCE", "inputStrength": "HIGH", "outputStrength": "HIGH"},
      {"type": "HATE", "inputStrength": "HIGH", "outputStrength": "HIGH"},
      {"type": "INSULTS", "inputStrength": "MEDIUM", "outputStrength": "MEDIUM"},
      {"type": "MISCONDUCT", "inputStrength": "HIGH", "outputStrength": "HIGH"},
      {"type": "PROMPT_ATTACK", "inputStrength": "HIGH", "outputStrength": "NONE"}
    ]
  }' \
  --blocked-input-messaging "Request blocked by content filter" \
  --blocked-output-messaging "Response blocked by content filter" \
  --tags Key=CostCentre,Value=GLOBAL
```

### Publish a Version

```bash
aws bedrock create-guardrail-version \
  --guardrail-identifier "guardrail-id" \
  --description "v1 - initial deployment"
```

---

## Cross-Region Inference Compatibility

If using cross-region inference profiles, **enable Cross-Region inference on your Guardrail** to ensure it works across all regions the profile routes to.

---

## Pricing

Guardrails are billed per text unit (1 text unit = 1,000 characters):
- Content filters: ~$0.15 per 1,000 text units
- Denied topics: ~$0.15 per 1,000 text units
- Sensitive info filter: ~$0.10 per 1,000 text units

---

## Relevance to Our Platform

| Requirement | Guardrails Feature |
|------------|-------------------|
| Content filtering per cost centre | Different guardrail IDs per cost centre config |
| Global content filtering | Single guardrail applied to all keys |
| Admin configurable | Guardrails managed via Bedrock console/API |
| Future/optional | Start without, add when needed |

---

## References

- https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-create.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreateGuardrail.html
