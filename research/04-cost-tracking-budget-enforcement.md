# AWS Bedrock — Cost Tracking & Budget Enforcement

## Overview

This document covers how to implement cost tracking, budget enforcement, and usage monitoring for Bedrock — key requirements for our platform's cost centre management.

**Sources:**
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-cw.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/tagging.html
- https://aws.amazon.com/bedrock/pricing/

---

## Cost Tracking Mechanisms

### 1. Application Inference Profiles (Primary Mechanism)

Create an inference profile per cost centre. All invocations via that profile are tracked together.

```bash
# Create per cost centre
aws bedrock create-inference-profile \
  --inference-profile-name "CC-1234" \
  --model-source '{"copyFrom": "arn:aws:bedrock:ap-southeast-2::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0"}' \
  --tags Key=CostCentre,Value=CC-1234 Key=ManagedBy,Value=claude-aws-manager
```

Activate tags for cost allocation in AWS Billing → Cost Allocation Tags.

### 2. Model Invocation Logging (Detailed Usage)

Enable logging to capture every API call with token counts:

```bash
aws bedrock put-model-invocation-logging-configuration \
  --logging-config '{
    "cloudWatchConfig": {
      "logGroupName": "/aws/bedrock/modelinvocations",
      "roleArn": "arn:aws:iam::123456789012:role/BedrockLoggingRole",
      "largeDataDeliveryS3Config": {
        "bucketName": "my-bedrock-logs",
        "keyPrefix": "invocation-logs"
      }
    },
    "s3Config": {
      "bucketName": "my-bedrock-logs",
      "keyPrefix": "invocation-logs"
    },
    "textDataDeliveryEnabled": true,
    "imageDataDeliveryEnabled": false,
    "embeddingDataDeliveryEnabled": false
  }'
```

### Log Entry Format

Each invocation log entry contains:

```json
{
  "schemaType": "ModelInvocationLog",
  "schemaVersion": "1.0",
  "timestamp": "2024-01-15T12:00:00Z",
  "accountId": "123456789012",
  "region": "ap-southeast-2",
  "requestId": "abcd1234-5678-efgh-ijkl-mnopqrstuvwx",
  "operation": "InvokeModelWithResponseStream",
  "modelId": "anthropic.claude-sonnet-4-20250514-v1:0",
  "requestMetadata": {
    "team": "engineering",
    "costCentre": "CC-1234"
  },
  "input": {
    "inputContentType": "application/json",
    "inputBodyJson": {},
    "inputTokenCount": 1500
  },
  "output": {
    "outputContentType": "application/json",
    "outputBodyJson": {},
    "outputTokenCount": 500
  }
}
```

**Key fields for cost tracking:**
- `inputTokenCount` — billable input tokens
- `outputTokenCount` — billable output tokens
- `modelId` — determines pricing tier
- `requestMetadata` — custom tags for attribution (if caller supplies them)

### 3. CloudWatch Metrics

Bedrock automatically publishes metrics to CloudWatch:

| Metric | Description |
|--------|-------------|
| `InputTokenCount` | Input tokens processed (excluding cached) |
| `OutputTokenCount` | Output tokens generated |
| `CacheReadInputTokens` | Tokens read from cache |
| `CacheWriteInputTokens` | Tokens written to cache |
| `InvocationCount` | Number of API calls |
| `InvocationLatency` | Response time |

**Dimensions available:**
- ModelId
- InferenceProfileId (when using inference profiles)

### 4. AWS Cost Explorer

With cost allocation tags activated on inference profiles:
- Filter by `CostCentre` tag
- View daily/monthly cost breakdown
- Export CSV reports

---

## Pricing (Anthropic Models on Bedrock)

Pricing is per 1,000 tokens:

| Model | Input (per 1K tokens) | Output (per 1K tokens) |
|-------|----------------------|----------------------|
| Claude Opus 4.x | ~$0.015 | ~$0.075 |
| Claude Sonnet 4.x | ~$0.003 | ~$0.015 |
| Claude Haiku 4.x | ~$0.0008 | ~$0.004 |

> **Note:** Prices vary by region and change over time. Always check https://aws.amazon.com/bedrock/pricing/ for current pricing.

### Cost Calculation Formula

```
Cost = (InputTokens / 1000 × InputPrice) + (OutputTokens / 1000 × OutputPrice)
```

### Prompt Caching Impact

- Cache read tokens: charged at reduced rate (~90% discount)
- Cache write tokens: charged at premium (~25% more)
- Net effect: significant savings for repeated prompts

---

## Budget Enforcement Architecture

### Option A: CloudWatch Alarms + Lambda (Near Real-Time)

```
CloudWatch Metrics → Alarm (threshold) → SNS → Lambda → Disable Key
```

1. **CloudWatch Alarm** watches token consumption per inference profile
2. **Lambda function** triggered when threshold exceeded
3. Lambda disables the IAM access key or modifies the policy to deny access

### Option B: Application-Level Enforcement (Our Platform)

```
Invocation Logs → Our App (polling/streaming) → Budget Check → Key Disable
```

1. Platform queries CloudWatch metrics or processes invocation logs
2. Calculates cost based on token counts × pricing
3. When limit reached, disables the key via IAM API

### Option C: Hybrid (Recommended)

- **Soft alerts:** CloudWatch Alarms → SNS → Email/Slack notification
- **Hard stops:** Application polls usage, disables keys when budget hit
- **Reconciliation:** Periodic check between app state and actual CloudWatch data

---

## Implementation: Per-Key Rolling Period Budget

For a rolling window of N days:

```python
import boto3
from datetime import datetime, timedelta

cloudwatch = boto3.client('cloudwatch', region_name='ap-southeast-2')

def get_token_usage(inference_profile_id, days=7):
    """Get token usage for the rolling period."""
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=days)
    
    # Get input tokens
    input_response = cloudwatch.get_metric_statistics(
        Namespace='AWS/Bedrock',
        MetricName='InputTokenCount',
        Dimensions=[
            {'Name': 'InferenceProfileId', 'Value': inference_profile_id}
        ],
        StartTime=start_time,
        EndTime=end_time,
        Period=86400,  # Daily granularity
        Statistics=['Sum']
    )
    
    # Get output tokens
    output_response = cloudwatch.get_metric_statistics(
        Namespace='AWS/Bedrock',
        MetricName='OutputTokenCount',
        Dimensions=[
            {'Name': 'InferenceProfileId', 'Value': inference_profile_id}
        ],
        StartTime=start_time,
        EndTime=end_time,
        Period=86400,
        Statistics=['Sum']
    )
    
    total_input = sum(dp['Sum'] for dp in input_response['Datapoints'])
    total_output = sum(dp['Sum'] for dp in output_response['Datapoints'])
    
    return total_input, total_output

def calculate_cost(input_tokens, output_tokens, model='sonnet'):
    """Calculate cost in dollars."""
    prices = {
        'opus': {'input': 0.015, 'output': 0.075},
        'sonnet': {'input': 0.003, 'output': 0.015},
        'haiku': {'input': 0.0008, 'output': 0.004}
    }
    p = prices[model]
    return (input_tokens / 1000 * p['input']) + (output_tokens / 1000 * p['output'])
```

---

## Tagging Resources for Cost Attribution

### Tag IAM Users

```bash
aws iam tag-user --user-name claude-dev-john --tags \
  Key=CostCentre,Value=CC-1234 \
  Key=Developer,Value=john.doe \
  Key=KeyCreated,Value=2026-05-23 \
  Key=KeyExpiry,Value=2026-08-21
```

### Tag Inference Profiles

```bash
aws bedrock tag-resource \
  --resource-arn "arn:aws:bedrock:ap-southeast-2:123456789012:application-inference-profile/profile-id" \
  --tags Key=CostCentre,Value=CC-1234 Key=Owner,Value=cost-centre-owner@company.com
```

### Activate Cost Allocation Tags

In AWS Billing Console → Cost Allocation Tags:
1. Select user-defined tags
2. Activate `CostCentre`, `Developer`, `Team` tags
3. Tags take ~24 hours to appear in Cost Explorer

---

## CloudWatch Alarm for Budget Threshold

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "CC-1234-budget-80pct" \
  --metric-name "OutputTokenCount" \
  --namespace "AWS/Bedrock" \
  --dimensions Name=InferenceProfileId,Value=profile-cc-1234 \
  --statistic Sum \
  --period 86400 \
  --evaluation-periods 1 \
  --threshold 1000000 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions "arn:aws:sns:ap-southeast-2:123456789012:budget-alerts"
```

---

## S3 Bucket Policy for Invocation Logs

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AmazonBedrockLogsWrite",
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock.amazonaws.com"
      },
      "Action": ["s3:PutObject"],
      "Resource": [
        "arn:aws:s3:::bedrock-logs-bucket/AWSLogs/123456789012/BedrockModelInvocationLogs/*"
      ],
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "123456789012"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:bedrock:ap-southeast-2:123456789012:*"
        }
      }
    }
  ]
}
```

---

## Cost Tracking Architecture for Our Platform

```
┌─────────────────────────────────────────────────┐
│ Developer uses Claude Code                       │
│ (with assigned inference profile ARN)            │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ AWS Bedrock                                      │
│ - Processes request                              │
│ - Logs to CloudWatch (metrics)                   │
│ - Logs to S3/CloudWatch Logs (full invocations)  │
│ - Tags cost to inference profile                 │
└──────────────────────┬──────────────────────────┘
                       │
            ┌──────────┼──────────┐
            ▼          ▼          ▼
    ┌───────────┐ ┌─────────┐ ┌───────────┐
    │CloudWatch │ │   S3    │ │   Cost    │
    │  Metrics  │ │  Logs   │ │ Explorer  │
    └─────┬─────┘ └────┬────┘ └─────┬─────┘
          │            │             │
          ▼            ▼             ▼
    ┌─────────────────────────────────────────┐
    │ Our Platform (polling/event-driven)      │
    │ - Calculates cost per key               │
    │ - Checks rolling period budgets         │
    │ - Disables keys when limits hit         │
    │ - Sends alerts at thresholds            │
    └─────────────────────────────────────────┘
```

---

## Key Decisions for Implementation

| Decision | Options | Recommendation |
|----------|---------|----------------|
| Cost data source | CloudWatch Metrics vs Invocation Logs | Both — metrics for real-time, logs for detailed breakdown |
| Polling frequency | Real-time vs periodic | Every 5 minutes for budget checks |
| Budget enforcement | App-level vs AWS-native | App-level (more flexible for rolling windows) |
| Cost calculation | AWS pricing API vs hardcoded | Start hardcoded, move to pricing API later |
| Alert mechanism | SNS → Lambda vs App polling | App polling with SNS for urgency |

---

## References

- https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/tagging.html
- https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/cost-alloc-tags.html
- https://aws.amazon.com/bedrock/pricing/
- https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/model-invocations.html
- https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock/blob/main/assets/docs/MONITORING.md
