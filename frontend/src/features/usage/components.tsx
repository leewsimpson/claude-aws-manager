// Shared presentational pieces for usage/cost display. Extracted from KeysPage
// so the Keys page (reviewer view) and the admin Usage page render the same
// spend meters and summary panels. Reuses the Bedrock Control Room class
// vocabulary (.usage-summary / .meter / .table) — no hand-rolled colours.

import { useCostCentreUsage, useUsageSummary } from './api'

export function formatCurrency(value: number | null): string {
  if (value === null) return '—'
  return `$${value.toFixed(2)}`
}

// Returns 0–1 fill ratio clamped to [0, 1].
export function spendRatio(spend: number, limit: number | null): number {
  if (limit === null || limit <= 0) return 0
  return Math.min(spend / limit, 1)
}

// Returns the CSS modifier for the meter fill based on ratio.
function meterMod(ratio: number): string {
  if (ratio >= 1) return 'meter__fill--danger'
  if (ratio >= 0.8) return 'meter__fill--warn'
  return ''
}

// Compact progress bar showing spend vs. limit.
export function SpendMeter({
  spend,
  limit,
  label,
}: {
  spend: number
  limit: number | null
  label: string
}) {
  const ratio = spendRatio(spend, limit)
  const mod = meterMod(ratio)
  return (
    <div className="meter">
      <div className="meter__bar" role="progressbar" aria-valuenow={spend} aria-valuemax={limit ?? 0} aria-label={label}>
        <div
          className={`meter__fill ${mod}`}
          style={{ width: limit !== null ? `${ratio * 100}%` : '0%' }}
        />
      </div>
      <span className="meter__label">
        {formatCurrency(spend)}{limit !== null ? ` / ${formatCurrency(limit)}` : ''}
      </span>
    </div>
  )
}

// Cost-centre spend summary (CCO/admin when a CC filter is active on Keys).
export function CostCentreUsageSummary({ ccId }: { ccId: string }) {
  const { data, isLoading } = useCostCentreUsage(ccId)

  if (isLoading || !data) return null

  const budgetRatio = spendRatio(data.total_spend, data.budget_cap)

  return (
    <div className="usage-summary">
      <p className="usage-summary__title">Cost centre spend — {data.cost_centre_code}</p>
      <div className="usage-summary__stat-row">
        <div className="usage-summary__stat">
          <span className="usage-summary__stat-label">Total spend</span>
          <span className="usage-summary__stat-value">{formatCurrency(data.total_spend)}</span>
        </div>
        <div className="usage-summary__stat">
          <span className="usage-summary__stat-label">Budget cap</span>
          <span className="usage-summary__stat-value">{formatCurrency(data.budget_cap)}</span>
        </div>
      </div>

      {data.budget_cap !== null && (
        <div style={{ marginBottom: '1rem' }}>
          <SpendMeter
            spend={data.total_spend}
            limit={data.budget_cap}
            label={`Total spend ${formatCurrency(data.total_spend)} of budget ${formatCurrency(data.budget_cap)}`}
          />
          {budgetRatio >= 0.8 && (
            <p style={{ margin: '0.35rem 0 0', fontSize: '0.82rem', color: budgetRatio >= 1 ? 'var(--danger)' : 'var(--warn)' }}>
              {budgetRatio >= 1 ? 'Budget cap reached.' : 'Approaching budget cap.'}
            </p>
          )}
        </div>
      )}

      {data.by_model.length > 0 && (
        <>
          <p className="usage-summary__title" style={{ marginBottom: '0.5rem' }}>By model</p>
          <table className="table" style={{ marginTop: 0 }}>
            <thead>
              <tr>
                <th>Model</th>
                <th>Total tokens</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.by_model.map((m) => (
                <tr key={m.model_id}>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.82rem' }}>{m.model_id}</td>
                  <td>{m.total_tokens.toLocaleString('en-AU')}</td>
                  <td style={{ fontFamily: 'var(--font-mono)' }}>{formatCurrency(m.cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

// Organisation-wide usage summary (admin only — backed by GET /usage/summary).
export function AdminUsageSummary() {
  const { data, isLoading } = useUsageSummary()

  if (isLoading || !data) return null

  return (
    <div className="usage-summary">
      <p className="usage-summary__title">Organisation usage summary</p>
      <div className="usage-summary__stat-row">
        <div className="usage-summary__stat">
          <span className="usage-summary__stat-label">Total spend</span>
          <span className="usage-summary__stat-value">{formatCurrency(data.total_spend)}</span>
        </div>
        <div className="usage-summary__stat">
          <span className="usage-summary__stat-label">Active keys</span>
          <span className="usage-summary__stat-value">{data.active_keys}</span>
        </div>
        <div className="usage-summary__stat">
          <span className="usage-summary__stat-label">Stopped keys</span>
          <span className="usage-summary__stat-value" style={{ color: data.stopped_keys > 0 ? 'var(--warn)' : 'inherit' }}>
            {data.stopped_keys}
          </span>
        </div>
      </div>

      {data.cost_centres.length > 0 && (
        <>
          <p className="usage-summary__title" style={{ marginBottom: '0.5rem' }}>By cost centre</p>
          <table className="table" style={{ marginTop: 0 }}>
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th>Spend vs budget</th>
                <th>Active</th>
                <th>Stopped</th>
              </tr>
            </thead>
            <tbody>
              {data.cost_centres.map((cc) => (
                <tr key={cc.cost_centre_id}>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.82rem' }}>{cc.code}</td>
                  <td>{cc.name}</td>
                  <td>
                    <SpendMeter
                      spend={cc.total_spend}
                      limit={cc.budget_cap}
                      label={`${cc.code}: ${formatCurrency(cc.total_spend)} / ${formatCurrency(cc.budget_cap)}`}
                    />
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)' }}>{cc.active_keys}</td>
                  <td style={{ fontFamily: 'var(--font-mono)', color: cc.stopped_keys > 0 ? 'var(--warn)' : 'inherit' }}>
                    {cc.stopped_keys}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {data.by_model.length > 0 && (
        <>
          <p className="usage-summary__title" style={{ margin: '1rem 0 0.5rem' }}>By model</p>
          <table className="table" style={{ marginTop: 0 }}>
            <thead>
              <tr>
                <th>Model</th>
                <th>Total tokens</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.by_model.map((m) => (
                <tr key={m.model_id}>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.82rem' }}>{m.model_id}</td>
                  <td>{m.total_tokens.toLocaleString('en-AU')}</td>
                  <td style={{ fontFamily: 'var(--font-mono)' }}>{formatCurrency(m.cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
