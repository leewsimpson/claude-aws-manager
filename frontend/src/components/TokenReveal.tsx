// One-time bearer token reveal panel. The token is shown exactly once after
// provisioning or regeneration — the user must store it before dismissing.
// Given a ProvisionedKey, renders the token with a Copy button, setup
// instructions (env var + modelOverrides JSON), and a dismiss button.

import { useState } from 'react'
import type { ProvisionedKey } from '../features/keyRequests/types'

interface TokenRevealProps {
  provisionedKey: ProvisionedKey
  onDismiss: () => void
}

export function TokenReveal({ provisionedKey, onDismiss }: TokenRevealProps) {
  const [copied, setCopied] = useState(false)

  const {
    bearer_token,
    iam_username,
    allowed_models,
    expires_at,
    inference_profiles,
  } = provisionedKey

  async function handleCopy() {
    await navigator.clipboard.writeText(bearer_token)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const modelOverrides: Record<string, string> = {}
  for (const profile of inference_profiles) {
    modelOverrides[profile.model_id] = profile.profile_arn
  }
  const modelOverridesJson = JSON.stringify(modelOverrides, null, 2)

  const expiryText = expires_at
    ? new Date(expires_at).toLocaleDateString('en-AU', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    : 'No expiry set'

  return (
    <div className="token-reveal" role="region" aria-label="Provisioned key details">
      <div className="token-reveal__warning" role="alert">
        <strong>Store this token now — it will not be shown again.</strong>
      </div>

      <div className="token-reveal__field">
        <span className="token-reveal__label">Bearer token</span>
        <div className="token-reveal__copy-row">
          <code className="token-reveal__code">{bearer_token}</code>
          <button
            type="button"
            className="btn btn--small"
            aria-label="Copy bearer token"
            onClick={() => void handleCopy()}
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      </div>

      <div className="token-reveal__field">
        <span className="token-reveal__label">IAM username</span>
        <code className="token-reveal__code">{iam_username}</code>
      </div>

      <div className="token-reveal__field">
        <span className="token-reveal__label">Allowed models</span>
        <span>{allowed_models.join(', ') || '—'}</span>
      </div>

      <div className="token-reveal__field">
        <span className="token-reveal__label">Expiry</span>
        <span>{expiryText}</span>
      </div>

      <div className="token-reveal__field">
        <span className="token-reveal__label">Setup — environment variable</span>
        <code className="token-reveal__code">
          AWS_BEARER_TOKEN_BEDROCK={bearer_token}
        </code>
      </div>

      {inference_profiles.length > 0 && (
        <div className="token-reveal__field">
          <span className="token-reveal__label">
            Setup — Claude Code modelOverrides (add to .claude/settings.json)
          </span>
          <pre className="token-reveal__pre">{modelOverridesJson}</pre>
        </div>
      )}

      <button
        type="button"
        className="btn"
        onClick={onDismiss}
        aria-label="Dismiss token panel"
      >
        Dismiss
      </button>
    </div>
  )
}
