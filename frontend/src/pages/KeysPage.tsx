import { useState, type FormEvent } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useCostCentres } from '../features/costCentres/api'
import { useKeys, useRevokeKey, useRegenerateKey, useUpdateKeyConstraints } from '../features/keys/api'
import type { Key, KeyStatus, UpdateKeyConstraintsInput } from '../features/keys/types'
import type { ProvisionedKey } from '../features/keyRequests/types'
import { TokenReveal } from '../components/TokenReveal'
import { useKeyUsage } from '../features/usage/api'
import {
  formatCurrency,
  SpendMeter,
  CostCentreUsageSummary,
  AdminUsageSummary,
} from '../features/usage/components'
import type { UsageSnapshot } from '../features/usage/types'

// Default model options — mirrors the seed allowed_models for the mock AWS service.
const DEFAULT_MODEL_OPTIONS = [
  'anthropic.claude-sonnet-4-6',
  'anthropic.claude-haiku-4-5',
]

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-AU', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function formatLimits(key: Key): string {
  const parts: string[] = []
  if (key.rolling_limit !== null && key.rolling_period_days !== null) {
    parts.push(`${formatCurrency(key.rolling_limit)} / ${key.rolling_period_days}d rolling`)
  }
  if (key.lifetime_budget !== null) {
    parts.push(`${formatCurrency(key.lifetime_budget)} lifetime`)
  }
  return parts.length > 0 ? parts.join('; ') : 'None'
}

// Derive a human-readable reason why a stopped key was stopped.
function stoppedReason(key: Key): string {
  if (key.rolling_limit !== null && key.rolling_spend >= key.rolling_limit) {
    return 'Stopped — rolling limit reached'
  }
  if (key.lifetime_budget !== null && key.lifetime_spend >= key.lifetime_budget) {
    return 'Stopped — lifetime budget reached'
  }
  return 'Stopped — cost-centre budget reached'
}

export function KeysPage() {
  const { user, hasRole } = useAuth()
  const isReviewer = hasRole('cco') || hasRole('admin')
  const isDeveloper = hasRole('developer') || (!isReviewer)

  // Lifted regenerated key state — persists across list invalidation
  const [regeneratedKey, setRegeneratedKey] = useState<ProvisionedKey | null>(null)

  if (regeneratedKey) {
    return (
      <section className="panel panel--wide">
        <div className="panel__header">
          <h1>Keys</h1>
        </div>
        <TokenReveal
          provisionedKey={regeneratedKey}
          onDismiss={() => setRegeneratedKey(null)}
        />
      </section>
    )
  }

  return (
    <section className="panel panel--wide">
      <div className="panel__header">
        <h1>Keys</h1>
      </div>

      {/* Developer view — visible to anyone with developer role, or non-reviewers */}
      {(isDeveloper || hasRole('developer')) && user && (
        <MyKeysSection
          userId={String(user.id)}
          onRegenerated={setRegeneratedKey}
        />
      )}

      {/* Reviewer view — visible to CCO and admin */}
      {isReviewer && (
        <ReviewerKeysSection />
      )}
    </section>
  )
}

// ---- Developer section ----

function MyKeysSection({
  userId,
  onRegenerated,
}: {
  userId: string
  onRegenerated: (key: ProvisionedKey) => void
}) {
  const { data: keys, isLoading, isError } = useKeys({ developer_id: userId })

  return (
    <>
      <h2>My keys</h2>
      {isLoading && (
        <p className="status status--loading">Loading keys…</p>
      )}
      {isError && (
        <p className="status status--error" role="alert">
          Unable to load keys.
        </p>
      )}
      {!isLoading && !isError && (keys ?? []).length === 0 && (
        <p className="status">No keys yet. Submit a key request to get started.</p>
      )}
      {(keys ?? []).map((key) => (
        <DeveloperKeyCard
          key={key.id}
          keyData={key}
          onRegenerated={onRegenerated}
        />
      ))}
    </>
  )
}

function DeveloperKeyCard({
  keyData,
  onRegenerated,
}: {
  keyData: Key
  onRegenerated: (key: ProvisionedKey) => void
}) {
  const [panel, setPanel] = useState<'none' | 'revoke' | 'setup'>('none')
  const [usageOpen, setUsageOpen] = useState(false)
  const revoke = useRevokeKey()
  const regenerate = useRegenerateKey()
  const [revokeError, setRevokeError] = useState<string | null>(null)
  const [regenError, setRegenError] = useState<string | null>(null)

  const modelOverrides: Record<string, string> = {}
  for (const profile of keyData.inference_profiles) {
    modelOverrides[profile.model_id] = profile.profile_arn
  }
  const modelOverridesJson = JSON.stringify({ modelOverrides }, null, 2)

  async function handleRevoke() {
    setRevokeError(null)
    try {
      await revoke.mutateAsync(keyData.id)
      setPanel('none')
    } catch {
      setRevokeError('Unable to revoke key. Please try again.')
    }
  }

  async function handleRegenerate() {
    setRegenError(null)
    try {
      const provisioned = await regenerate.mutateAsync(keyData.id)
      onRegenerated(provisioned)
    } catch {
      setRegenError('Unable to regenerate key. Please try again.')
    }
  }

  const canAct = keyData.status === 'active' || keyData.status === 'stopped'
  const isStopped = keyData.status === 'stopped'

  const hasRollingBudget = keyData.rolling_limit !== null && keyData.rolling_period_days !== null
  const hasLifetimeBudget = keyData.lifetime_budget !== null

  return (
    <div className="key-card">
      <div className="key-card__header">
        <div className="key-card__title">
          <span className="key-card__cc">
            {keyData.cost_centre_code} — {keyData.cost_centre_name}
          </span>
          <span className={`badge badge--${keyData.status}`}>{keyData.status}</span>
        </div>
        {canAct && (
          <div className="key-card__actions">
            <button
              type="button"
              className="btn btn--small"
              onClick={() => setPanel(panel === 'setup' ? 'none' : 'setup')}
            >
              {panel === 'setup' ? 'Close setup' : 'Setup instructions'}
            </button>
            <button
              type="button"
              className="btn btn--small"
              onClick={() => void handleRegenerate()}
              disabled={regenerate.isPending}
            >
              {regenerate.isPending ? 'Regenerating…' : 'Regenerate'}
            </button>
            <button
              type="button"
              className="btn btn--small btn--danger"
              onClick={() => setPanel(panel === 'revoke' ? 'none' : 'revoke')}
            >
              {panel === 'revoke' ? 'Close' : 'Revoke'}
            </button>
          </div>
        )}
      </div>

      {/* Stopped key banner */}
      {isStopped && (
        <div className="key-card__stopped-banner" role="alert">
          {stoppedReason(keyData)}
          <p className="key-card__stopped-note">
            Usage is updated approximately every 2 minutes. The key will resume automatically
            when rolling spend falls below the limit, or when a budget is increased.
          </p>
        </div>
      )}

      <div className="key-card__meta">
        <div className="key-card__meta-row">
          <span className="key-card__label">Models</span>
          <span className="key-card__value key-card__value--mono">
            {keyData.allowed_models.length > 0
              ? keyData.allowed_models.join(', ')
              : '—'}
          </span>
        </div>

        {/* Rolling spend / limit */}
        <div className="key-card__meta-row">
          <span className="key-card__label">Rolling spend</span>
          {hasRollingBudget ? (
            <span className="key-card__value">
              <SpendMeter
                spend={keyData.rolling_spend}
                limit={keyData.rolling_limit}
                label={`Rolling spend: ${formatCurrency(keyData.rolling_spend)} of ${formatCurrency(keyData.rolling_limit)} over ${keyData.rolling_period_days} days`}
              />
              <span className="meter__label" style={{ marginTop: '0.1rem', display: 'block' }}>
                / {keyData.rolling_period_days} days
              </span>
            </span>
          ) : (
            <span className="key-card__value">{formatCurrency(keyData.rolling_spend)} (no limit)</span>
          )}
        </div>

        {/* Lifetime spend / budget */}
        <div className="key-card__meta-row">
          <span className="key-card__label">Lifetime spend</span>
          {hasLifetimeBudget ? (
            <span className="key-card__value">
              <SpendMeter
                spend={keyData.lifetime_spend}
                limit={keyData.lifetime_budget}
                label={`Lifetime spend: ${formatCurrency(keyData.lifetime_spend)} of ${formatCurrency(keyData.lifetime_budget)}`}
              />
            </span>
          ) : (
            <span className="key-card__value">{formatCurrency(keyData.lifetime_spend)} (no budget)</span>
          )}
        </div>

        <div className="key-card__meta-row">
          <span className="key-card__label">Expires</span>
          <span className="key-card__value">{formatDate(keyData.expires_at)}</span>
        </div>
        <div className="key-card__meta-row">
          <span className="key-card__label">Created</span>
          <span className="key-card__value">{formatDate(keyData.created_at)}</span>
        </div>
      </div>

      {/* Recent usage (collapsible) */}
      <div className="key-card__usage">
        <button
          type="button"
          className="key-card__usage-toggle"
          onClick={() => setUsageOpen((v) => !v)}
          aria-expanded={usageOpen}
        >
          {usageOpen ? '▾' : '▸'} Recent usage
        </button>
        {usageOpen && (
          <KeyUsagePanel keyId={keyData.id} />
        )}
      </div>

      {regenError && (
        <p className="status status--error" role="alert">
          {regenError}
        </p>
      )}

      {panel === 'revoke' && (
        <div className="key-card__panel">
          <p className="key-card__confirm-text">
            Are you sure? This will permanently revoke the key and cannot be undone.
          </p>
          {revokeError && (
            <p className="status status--error" role="alert">
              {revokeError}
            </p>
          )}
          <div className="form__row">
            <button
              type="button"
              className="btn btn--small btn--danger"
              onClick={() => void handleRevoke()}
              disabled={revoke.isPending}
            >
              {revoke.isPending ? 'Revoking…' : 'Revoke'}
            </button>
            <button
              type="button"
              className="btn btn--small"
              onClick={() => setPanel('none')}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {panel === 'setup' && (
        <div className="key-card__panel">
          <h3 className="form__title">Setup instructions</h3>
          <div className="key-card__setup-field">
            <span className="key-card__label">Environment variable (name only — run Regenerate to get the token)</span>
            <code className="token-reveal__code">AWS_BEARER_TOKEN_BEDROCK</code>
          </div>
          {keyData.inference_profiles.length > 0 && (
            <div className="key-card__setup-field">
              <span className="key-card__label">
                Claude Code modelOverrides (add to .claude/settings.json)
              </span>
              <pre className="token-reveal__pre">{modelOverridesJson}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function KeyUsagePanel({ keyId }: { keyId: string }) {
  const { data, isLoading, isError } = useKeyUsage(keyId)

  if (isLoading) {
    return <p className="status status--loading key-card__usage-list">Loading usage…</p>
  }
  if (isError || !data) {
    return <p className="status status--error key-card__usage-list">Unable to load usage.</p>
  }
  if (data.snapshots.length === 0) {
    return <p className="key-card__usage-list" style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>No usage snapshots yet.</p>
  }

  // Show most-recent first, cap at 10.
  const recent = [...data.snapshots]
    .sort((a, b) => b.period_start.localeCompare(a.period_start))
    .slice(0, 10)

  return (
    <div className="key-card__usage-list">
      <table className="table" style={{ marginTop: 0 }}>
        <thead>
          <tr>
            <th>Period</th>
            <th>Model</th>
            <th>Input tokens</th>
            <th>Output tokens</th>
            <th>Cost</th>
          </tr>
        </thead>
        <tbody>
          {recent.map((snap: UsageSnapshot, i: number) => (
            <tr key={i}>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                {formatDate(snap.period_start)}
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                {snap.model_id}
              </td>
              <td>{snap.input_tokens.toLocaleString('en-AU')}</td>
              <td>{snap.output_tokens.toLocaleString('en-AU')}</td>
              <td style={{ fontFamily: 'var(--font-mono)' }}>{formatCurrency(snap.cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---- Reviewer section ----

function ReviewerKeysSection() {
  const { hasRole } = useAuth()
  const isAdmin = hasRole('admin')

  const [statusFilter, setStatusFilter] = useState<KeyStatus | ''>('')
  const [ccFilter, setCcFilter] = useState<string>('')

  const { data: costCentres } = useCostCentres()

  const { data: keys, isLoading, isError } = useKeys({
    status: statusFilter || undefined,
    cost_centre_id: ccFilter || undefined,
  })

  return (
    <>
      <h2>Key management</h2>

      <div className="form__row keys-filters">
        <label className="form__field">
          <span>Status</span>
          <select
            aria-label="Filter by status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as KeyStatus | '')}
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="stopped">Stopped</option>
            <option value="revoked">Revoked</option>
            <option value="expired">Expired</option>
          </select>
        </label>

        {isAdmin && (
          <label className="form__field">
            <span>Cost centre</span>
            <select
              aria-label="Filter by cost centre"
              value={ccFilter}
              onChange={(e) => setCcFilter(e.target.value)}
            >
              <option value="">All cost centres</option>
              {(costCentres ?? []).map((cc) => (
                <option key={cc.id} value={cc.id}>
                  {cc.code} — {cc.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {isLoading && (
        <p className="status status--loading">Loading keys…</p>
      )}
      {isError && (
        <p className="status status--error" role="alert">
          Unable to load keys.
        </p>
      )}
      {!isLoading && !isError && (keys ?? []).length === 0 && (
        <p className="status">No keys match the current filters.</p>
      )}

      {(keys ?? []).length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Developer</th>
              <th>Cost centre</th>
              <th>Status</th>
              <th>Limits</th>
              <th>Spend</th>
              <th>Expires</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {(keys ?? []).map((key) => (
              <ReviewerKeyRow key={key.id} keyData={key} />
            ))}
          </tbody>
        </table>
      )}

      {/* CC usage summary panel — shown when a CC filter is active */}
      {ccFilter && (
        <CostCentreUsageSummary ccId={ccFilter} />
      )}

      {/* Admin-only global usage summary */}
      {isAdmin && (
        <AdminUsageSummary />
      )}
    </>
  )
}

function ReviewerKeyRow({ keyData }: { keyData: Key }) {
  const [panel, setPanel] = useState<'none' | 'revoke' | 'edit'>('none')

  const canAct = keyData.status !== 'revoked'

  const hasRollingBudget = keyData.rolling_limit !== null
  const hasLifetimeBudget = keyData.lifetime_budget !== null

  return (
    <>
      <tr>
        <td>
          {keyData.developer_display_name} ({keyData.developer_username})
        </td>
        <td>
          {keyData.cost_centre_code} — {keyData.cost_centre_name}
        </td>
        <td>
          <span className={`badge badge--${keyData.status}`}>{keyData.status}</span>
        </td>
        <td>{formatLimits(keyData)}</td>
        <td>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', minWidth: '8rem' }}>
            {hasRollingBudget && (
              <SpendMeter
                spend={keyData.rolling_spend}
                limit={keyData.rolling_limit}
                label={`Rolling: ${formatCurrency(keyData.rolling_spend)} / ${formatCurrency(keyData.rolling_limit)}`}
              />
            )}
            {hasLifetimeBudget && (
              <SpendMeter
                spend={keyData.lifetime_spend}
                limit={keyData.lifetime_budget}
                label={`Lifetime: ${formatCurrency(keyData.lifetime_spend)} / ${formatCurrency(keyData.lifetime_budget)}`}
              />
            )}
            {!hasRollingBudget && !hasLifetimeBudget && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                R: {formatCurrency(keyData.rolling_spend)} / L: {formatCurrency(keyData.lifetime_spend)}
              </span>
            )}
          </div>
        </td>
        <td>{formatDate(keyData.expires_at)}</td>
        <td className="table__actions">
          {canAct && (
            <>
              <button
                type="button"
                className="btn btn--small"
                onClick={() => setPanel(panel === 'edit' ? 'none' : 'edit')}
              >
                {panel === 'edit' ? 'Close' : 'Edit constraints'}
              </button>
              <button
                type="button"
                className="btn btn--small btn--danger"
                onClick={() => setPanel(panel === 'revoke' ? 'none' : 'revoke')}
              >
                {panel === 'revoke' ? 'Cancel' : 'Revoke'}
              </button>
            </>
          )}
        </td>
      </tr>
      {panel === 'revoke' && (
        <tr>
          <td colSpan={7}>
            <ReviewerRevokePanel
              keyData={keyData}
              onDone={() => setPanel('none')}
            />
          </td>
        </tr>
      )}
      {panel === 'edit' && (
        <tr>
          <td colSpan={7}>
            <EditConstraintsPanel
              keyData={keyData}
              onDone={() => setPanel('none')}
            />
          </td>
        </tr>
      )}
    </>
  )
}

function ReviewerRevokePanel({
  keyData,
  onDone,
}: {
  keyData: Key
  onDone: () => void
}) {
  const revoke = useRevokeKey()
  const [error, setError] = useState<string | null>(null)

  async function handleRevoke() {
    setError(null)
    try {
      await revoke.mutateAsync(keyData.id)
      onDone()
    } catch {
      setError('Unable to revoke key. Please try again.')
    }
  }

  return (
    <div className="form form--inline">
      <h3 className="form__title">
        Revoke key — {keyData.developer_username} / {keyData.cost_centre_code}
      </h3>
      <p className="key-card__confirm-text">
        Are you sure? This will permanently revoke the key and cannot be undone.
      </p>
      {error && (
        <p className="status status--error" role="alert">
          {error}
        </p>
      )}
      <div className="form__row">
        <button
          type="button"
          className="btn btn--small btn--danger"
          onClick={() => void handleRevoke()}
          disabled={revoke.isPending}
        >
          {revoke.isPending ? 'Revoking…' : 'Revoke'}
        </button>
        <button type="button" className="btn btn--small" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  )
}

function EditConstraintsPanel({
  keyData,
  onDone,
}: {
  keyData: Key
  onDone: () => void
}) {
  const updateConstraints = useUpdateKeyConstraints()

  const [selectedModels, setSelectedModels] = useState<Set<string>>(
    new Set(keyData.allowed_models),
  )
  const [rollingLimit, setRollingLimit] = useState(
    keyData.rolling_limit !== null ? String(keyData.rolling_limit) : '',
  )
  const [rollingPeriodDays, setRollingPeriodDays] = useState(
    keyData.rolling_period_days !== null ? String(keyData.rolling_period_days) : '',
  )
  const [lifetimeBudget, setLifetimeBudget] = useState(
    keyData.lifetime_budget !== null ? String(keyData.lifetime_budget) : '',
  )
  const [expiryDays, setExpiryDays] = useState('')
  const [error, setError] = useState<string | null>(null)

  function toggleModel(model: string) {
    setSelectedModels((prev) => {
      const next = new Set(prev)
      if (next.has(model)) {
        next.delete(model)
      } else {
        next.add(model)
      }
      return next
    })
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)

    const input: UpdateKeyConstraintsInput = {}
    if (selectedModels.size > 0) {
      input.allowed_models = Array.from(selectedModels)
    }
    if (rollingLimit.trim()) {
      input.rolling_limit = Number(rollingLimit)
    } else {
      input.rolling_limit = null
    }
    if (rollingPeriodDays.trim()) {
      input.rolling_period_days = Number(rollingPeriodDays)
    } else {
      input.rolling_period_days = null
    }
    if (lifetimeBudget.trim()) {
      input.lifetime_budget = Number(lifetimeBudget)
    } else {
      input.lifetime_budget = null
    }
    if (expiryDays.trim()) {
      input.expiry_days = Number(expiryDays)
    }

    try {
      await updateConstraints.mutateAsync({ id: keyData.id, input })
      onDone()
    } catch {
      setError('Unable to update constraints. Please try again.')
    }
  }

  return (
    <form className="form form--inline" onSubmit={handleSubmit}>
      <h3 className="form__title">
        Edit constraints — {keyData.developer_username} / {keyData.cost_centre_code}
      </h3>

      <fieldset className="approve-panel__fieldset">
        <legend className="approve-panel__legend">Allowed models</legend>
        {DEFAULT_MODEL_OPTIONS.map((model) => (
          <label key={model} className="approve-panel__model-row">
            <input
              type="checkbox"
              checked={selectedModels.has(model)}
              onChange={() => toggleModel(model)}
            />
            {model}
          </label>
        ))}
      </fieldset>

      <div className="form__row">
        <label className="form__field">
          <span>Rolling limit (AUD)</span>
          <input
            type="number"
            min="0"
            step="0.01"
            value={rollingLimit}
            onChange={(e) => setRollingLimit(e.target.value)}
            placeholder="Leave blank for none"
            aria-label="Rolling limit"
          />
        </label>
        <label className="form__field">
          <span>Rolling period (days)</span>
          <input
            type="number"
            min="1"
            step="1"
            value={rollingPeriodDays}
            onChange={(e) => setRollingPeriodDays(e.target.value)}
            placeholder="Leave blank for none"
            aria-label="Rolling period days"
          />
        </label>
      </div>
      <div className="form__row">
        <label className="form__field">
          <span>Lifetime budget (AUD)</span>
          <input
            type="number"
            min="0"
            step="0.01"
            value={lifetimeBudget}
            onChange={(e) => setLifetimeBudget(e.target.value)}
            placeholder="Leave blank for none"
            aria-label="Lifetime budget"
          />
        </label>
        <label className="form__field">
          <span>New expiry (days from now)</span>
          <input
            type="number"
            min="1"
            step="1"
            value={expiryDays}
            onChange={(e) => setExpiryDays(e.target.value)}
            placeholder="Leave blank to keep current"
            aria-label="Expiry days"
          />
        </label>
      </div>

      {error && (
        <p className="status status--error" role="alert">
          {error}
        </p>
      )}

      <div className="form__row">
        <button type="submit" disabled={updateConstraints.isPending}>
          {updateConstraints.isPending ? 'Saving…' : 'Save constraints'}
        </button>
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  )
}
