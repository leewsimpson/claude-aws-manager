# Tech Spike — Hands-On Validation

Items that are documented/confirmed but need hands-on validation before PoC build.

---

## 1. End-to-End Provisioning + Inference Profile Flow

**Status:** Not yet tested  
**Risk:** Medium — all individual pieces are documented, but the full chain hasn't been exercised  
**Blocking:** PoC build (this is the core provisioning flow)

### What to validate

Run the full provisioning flow against a real AWS account and confirm Claude Code works:

```bash
# 1. Create IAM user
aws iam create-user --user-name claude-spike-test-01

# 2. Attach scoped policy (allow Sonnet via inference profile + foundation model)
aws iam put-user-policy --user-name claude-spike-test-01 \
  --policy-name TestPolicy --policy-document '{...}'

# 3. Generate Bedrock API key
aws iam create-service-specific-credential \
  --user-name claude-spike-test-01 \
  --service-name bedrock.amazonaws.com \
  --credential-age-days 1

# 4. Create application inference profile for cost tracking
aws bedrock create-inference-profile \
  --inference-profile-name "spike-test-sonnet" \
  --model-source '{"copyFrom": "arn:aws:bedrock:ap-southeast-2::foundation-model/anthropic.claude-sonnet-4-6"}' \
  --tags Key=CostCentre,Value=SPIKE-TEST

# 5. Configure Claude Code with bearer token + inference profile
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION=ap-southeast-2
export AWS_BEARER_TOKEN_BEDROCK=<token-from-step-3>
# Plus modelOverrides in settings file pointing to inference profile from step 4

# 6. Run Claude Code, make a request, verify it works
claude
```

### Success criteria

- [ ] Claude Code sends requests successfully with the bearer token
- [ ] Requests route through the inference profile (visible in CloudWatch metrics under the profile's dimension)
- [ ] IAM policy correctly restricts model access (attempt to use Opus fails with 403)
- [ ] CloudWatch `InputTokenCount` and `OutputTokenCount` metrics appear under the inference profile
- [ ] Invocation logs capture the IAM user identity for per-key attribution
- [ ] Deactivating the credential (`UpdateServiceSpecificCredential Status=Inactive`) immediately stops Claude Code from working
- [ ] `ResetServiceSpecificCredential` returns a new token; old token stops working

### Cleanup

```bash
aws iam delete-service-specific-credential --user-name claude-spike-test-01 --service-specific-credential-id <id>
aws iam delete-user-policy --user-name claude-spike-test-01 --policy-name TestPolicy
aws iam delete-user --user-name claude-spike-test-01
aws bedrock delete-inference-profile --inference-profile-identifier <arn>
```

---

## 2. CloudWatch Metrics Latency + Granularity

**Status:** Not yet tested  
**Risk:** Low — documented in AWS docs, but real-world latency may differ  
**Blocking:** Budget enforcement accuracy

### What to validate

After running a few requests through the inference profile (spike #1):

- [ ] How quickly do `InputTokenCount` / `OutputTokenCount` metrics appear in CloudWatch? (documented as "near real-time" — verify it's < 5 minutes)
- [ ] Are metrics available with `InferenceProfileId` dimension? (needed for per-CC queries)
- [ ] Does `Period=300` (5-minute) granularity work for `get_metric_statistics`?
- [ ] Can we get metrics broken down by model ID within the same inference profile?

### Why it matters

Budget enforcement polls every 5 minutes. If CloudWatch metrics have > 5 minute lag, we may need to fall back to parsing invocation logs for budget enforcement (more complex).

---

## 3. Invocation Log Delivery + IAM User Attribution

**Status:** Not yet tested  
**Risk:** Low — well-documented, but format and delivery timing should be verified  
**Blocking:** Per-key cost drill-down

### What to validate

Enable model invocation logging to CloudWatch Logs and/or S3:

- [ ] Confirm log entries include the IAM user identity (the user created by the Bedrock API Key)
- [ ] Confirm `inputTokenCount` and `outputTokenCount` are present per log entry
- [ ] Confirm `modelId` is present (needed to apply correct pricing)
- [ ] Measure log delivery latency (should be < 5 minutes)
- [ ] Verify log format matches what's documented in research/04

---

## Resolved Questions (No Spike Needed)

These were open questions that have been confirmed via documentation review (May 2026):

| Question | Answer | Source |
|----------|--------|--------|
| Does bearer token auth work with inference profile ARNs? | **Yes** — explicitly documented | Claude Code Bedrock docs |
| Is `bedrock:CallWithBearerToken` a real IAM action? | **Yes** — controls bearer token usage, with `bearerTokenType` condition key | AWS api-keys-permissions docs |
| Does Claude Code support `modelOverrides` for per-model inference profiles? | **Yes** — maps Anthropic model IDs to inference profile ARNs | Claude Code model-config docs |
| Does `bedrock:GetInferenceProfile` help with bearer token? | **Yes** — avoids retry overhead when resolving profile to model | Claude Code Bedrock docs |
| Application inference profiles supported in ap-southeast-2? | **Yes** — listed in supported regions | AWS inference-profiles-support docs |
