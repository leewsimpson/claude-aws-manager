// One-time bearer token reveal panel. The token is shown exactly once after
// provisioning or regeneration — the user must store it before dismissing.
// Given a ProvisionedKey, renders the token with Copy buttons, setup
// instructions (env var + modelOverrides JSON), and a dismiss button.
//
// Navigation guard: registers a beforeunload handler while mounted so the
// browser prompts before a tab close/refresh. In-app nav is NOT blocked here
// because the app uses <Routes> (not a data router) and useBlocker is
// unavailable. TODO: add a router-level blocker when the app migrates to
// React Router v6 data router / v7.

import { useState, useEffect } from 'react'
import type { ProvisionedKey } from '../features/keyRequests/types'

interface TokenRevealProps {
  provisionedKey: ProvisionedKey
  onDismiss: () => void
}

export function TokenReveal({ provisionedKey, onDismiss }: TokenRevealProps) {
  const [copied, setCopied] = useState(false)
  const [copiedEnvLine, setCopiedEnvLine] = useState(false)
  const [copyError, setCopyError] = useState<string | null>(null)

  const {
    bearer_token,
    iam_username,
    allowed_models,
    expires_at,
    inference_profiles,
  } = provisionedKey

  // Register a beforeunload handler for the lifetime of this component so the
  // browser's native "leave site?" dialog fires on tab close or refresh.
  useEffect(() => {
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault()
      // Returning a string is the legacy API; modern browsers ignore the value
      // but still show their own dialog when preventDefault() is called.
      return ''
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [])

  async function writeToClipboard(text: string): Promise<boolean> {
    try {
      if (!navigator.clipboard) {
        setCopyError('Copy failed — please select and copy the token manually.')
        return false
      }
      await navigator.clipboard.writeText(text)
      setCopyError(null)
      return true
    } catch {
      setCopyError('Copy failed — please select and copy the token manually.')
      return false
    }
  }

  async function handleCopyToken() {
    const ok = await writeToClipboard(bearer_token)
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const envLine = `AWS_BEARER_TOKEN_BEDROCK=${bearer_token}`

  async function handleCopyEnvLine() {
    const ok = await writeToClipboard(envLine)
    if (ok) {
      setCopiedEnvLine(true)
      setTimeout(() => setCopiedEnvLine(false), 2000)
    }
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
      <div className="token-reveal__warning token-reveal__warning--prominent" role="alert">
        <strong>Store this token now — it will not be shown again.</strong>
        <p className="token-reveal__warning-detail">
          If you navigate away or close this tab, this token cannot be retrieved — you would need to regenerate the key.
        </p>
      </div>

      {copyError && (
        <p className="status status--error" role="alert">
          {copyError}
        </p>
      )}

      <div className="token-reveal__field">
        <span className="token-reveal__label">Bearer token</span>
        <div className="token-reveal__copy-row">
          <code className="token-reveal__code">{bearer_token}</code>
          <button
            type="button"
            className="btn btn--small"
            aria-label="Copy bearer token"
            onClick={() => void handleCopyToken()}
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
        <div className="token-reveal__copy-row">
          <code className="token-reveal__code">{envLine}</code>
          <button
            type="button"
            className="btn btn--small"
            aria-label="Copy AWS_BEARER_TOKEN_BEDROCK env var line"
            onClick={() => void handleCopyEnvLine()}
          >
            {copiedEnvLine ? 'Copied!' : 'Copy'}
          </button>
        </div>
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
