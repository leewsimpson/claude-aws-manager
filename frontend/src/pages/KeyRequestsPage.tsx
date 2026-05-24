import { useState, type FormEvent } from 'react'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../lib/api'
import { useCostCentres } from '../features/costCentres/api'
import {
  useKeyRequests,
  useCreateKeyRequest,
  useApproveKeyRequest,
  useRejectKeyRequest,
} from '../features/keyRequests/api'
import type { KeyRequest, ProvisionedKey } from '../features/keyRequests/types'
import { TokenReveal } from '../components/TokenReveal'

// Default model options for the approve panel — mirrors the seed allowed_models
// for the mock AWS service. A Phase-9 settings endpoint will replace this constant.
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

export function KeyRequestsPage() {
  const { user, hasRole } = useAuth()
  const isReviewer = hasRole('cco') || hasRole('admin')

  const { data: allRequests, isLoading, isError } = useKeyRequests()

  // Reviewer-level provisioned key to show after approving — lifted here so the
  // TokenReveal persists even after the invalidation removes the row.
  const [reviewerKey, setReviewerKey] = useState<ProvisionedKey | null>(null)

  const myRequests = (allRequests ?? []).filter(
    (r) => String(r.developer_id) === String(user?.id),
  )
  const pendingRequests = (allRequests ?? []).filter((r) => r.status === 'pending')

  if (reviewerKey) {
    return (
      <section className="panel panel--wide">
        <div className="panel__header">
          <h1>Key requests</h1>
        </div>
        <TokenReveal
          provisionedKey={reviewerKey}
          onDismiss={() => setReviewerKey(null)}
        />
      </section>
    )
  }

  return (
    <section className="panel panel--wide">
      <div className="panel__header">
        <h1>Key requests</h1>
      </div>

      {isLoading && (
        <p className="status status--loading">Loading key requests…</p>
      )}
      {isError && (
        <p className="status status--error" role="alert">
          Unable to load key requests.
        </p>
      )}

      {/* Developer section — visible to everyone */}
      <RequestKeyForm />

      <h2>My requests</h2>
      {!isLoading && myRequests.length === 0 && (
        <p className="status">No requests yet.</p>
      )}
      {myRequests.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Cost centre</th>
              <th>Status</th>
              <th>Justification</th>
              <th>Reviewed</th>
              <th>Rejection reason</th>
            </tr>
          </thead>
          <tbody>
            {myRequests.map((req) => (
              <tr key={req.id}>
                <td>
                  {req.cost_centre_code} — {req.cost_centre_name}
                </td>
                <td>
                  <span className={`badge badge--${req.status}`}>{req.status}</span>
                </td>
                <td>{req.justification ?? '—'}</td>
                <td>{formatDate(req.reviewed_at)}</td>
                <td>{req.rejection_reason ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Reviewer section — visible to CCO and admin */}
      {isReviewer && (
        <>
          <h2>Pending requests</h2>
          {!isLoading && pendingRequests.length === 0 && (
            <p className="status">No pending requests.</p>
          )}
          {pendingRequests.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>Developer</th>
                  <th>Cost centre</th>
                  <th>Justification</th>
                  <th>Submitted</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pendingRequests.map((req) => (
                  <PendingRequestRow
                    key={req.id}
                    request={req}
                    onProvisioned={setReviewerKey}
                  />
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  )
}

function RequestKeyForm() {
  const create = useCreateKeyRequest()
  const { data: costCentres } = useCostCentres()
  const [costCentreId, setCostCentreId] = useState('')
  const [justification, setJustification] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [provisionedKey, setProvisionedKey] = useState<ProvisionedKey | null>(null)

  const activeCostCentres = (costCentres ?? []).filter(
    (cc) => cc.status === 'active',
  )

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      const result = await create.mutateAsync({
        cost_centre_id: costCentreId,
        justification: justification.trim() || undefined,
      })
      setCostCentreId('')
      setJustification('')
      // Only show TokenReveal when the request was auto-approved and a key was
      // returned. A pending result with key===null is the normal path.
      if (result.request.status === 'approved' && result.key) {
        setProvisionedKey(result.key)
      } else if (result.request.status === 'approved' && !result.key) {
        setError('Approved, but no key token was returned — contact your administrator.')
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('You already have an active or pending request for this cost centre.')
      } else {
        setError('Unable to submit request. Please try again.')
      }
    }
  }

  if (provisionedKey) {
    return (
      <TokenReveal
        provisionedKey={provisionedKey}
        onDismiss={() => setProvisionedKey(null)}
      />
    )
  }

  return (
    <form className="form form--inline" onSubmit={handleSubmit}>
      <h2 className="form__title">Request a key</h2>
      <div className="form__row">
        <label className="form__field">
          <span>Cost centre</span>
          <select
            aria-label="Cost centre"
            value={costCentreId}
            onChange={(e) => setCostCentreId(e.target.value)}
            required
          >
            <option value="">Select a cost centre…</option>
            {activeCostCentres.map((cc) => (
              <option key={cc.id} value={cc.id}>
                {cc.code} — {cc.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="form__field">
        <span>Justification (optional)</span>
        <textarea
          aria-label="Justification"
          value={justification}
          onChange={(e) => setJustification(e.target.value)}
          rows={3}
        />
      </label>
      {error && (
        <p className="status status--error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" disabled={create.isPending}>
        {create.isPending ? 'Submitting…' : 'Submit request'}
      </button>
    </form>
  )
}

function PendingRequestRow({
  request,
  onProvisioned,
}: {
  request: KeyRequest
  onProvisioned: (key: ProvisionedKey) => void
}) {
  const [panel, setPanel] = useState<'none' | 'approve' | 'reject'>('none')

  return (
    <>
      <tr>
        <td>
          {request.developer_display_name} ({request.developer_username})
        </td>
        <td>
          {request.cost_centre_code} — {request.cost_centre_name}
        </td>
        <td>{request.justification ?? '—'}</td>
        <td>{formatDate(request.created_at)}</td>
        <td className="table__actions">
          <button
            type="button"
            className="btn btn--small"
            onClick={() => setPanel(panel === 'approve' ? 'none' : 'approve')}
          >
            {panel === 'approve' ? 'Close' : 'Approve'}
          </button>
          <button
            type="button"
            className="btn btn--small btn--danger"
            onClick={() => setPanel(panel === 'reject' ? 'none' : 'reject')}
          >
            {panel === 'reject' ? 'Close' : 'Reject'}
          </button>
        </td>
      </tr>
      {panel === 'approve' && (
        <tr>
          <td colSpan={5}>
            <ApprovePanel
              request={request}
              onDone={() => setPanel('none')}
              onProvisioned={(key) => {
                setPanel('none')
                onProvisioned(key)
              }}
            />
          </td>
        </tr>
      )}
      {panel === 'reject' && (
        <tr>
          <td colSpan={5}>
            <RejectPanel request={request} onDone={() => setPanel('none')} />
          </td>
        </tr>
      )}
    </>
  )
}

function ApprovePanel({
  request,
  onDone,
  onProvisioned,
}: {
  request: KeyRequest
  onDone: () => void
  onProvisioned: (key: ProvisionedKey) => void
}) {
  const approve = useApproveKeyRequest()

  // Model checkboxes — default all selected to avoid accidentally sending an
  // empty list and triggering backend defaults unexpectedly.
  const [selectedModels, setSelectedModels] = useState<Set<string>>(
    new Set(DEFAULT_MODEL_OPTIONS),
  )
  const [rollingLimit, setRollingLimit] = useState('')
  const [rollingPeriodDays, setRollingPeriodDays] = useState('')
  const [lifetimeBudget, setLifetimeBudget] = useState('')
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
    try {
      const result = await approve.mutateAsync({
        id: request.id,
        input: {
          // Omit allowed_models if none selected — backend applies defaults.
          ...(selectedModels.size > 0 && {
            allowed_models: Array.from(selectedModels),
          }),
          ...(rollingLimit.trim() && { rolling_limit: Number(rollingLimit) }),
          ...(rollingPeriodDays.trim() && {
            rolling_period_days: Number(rollingPeriodDays),
          }),
          ...(lifetimeBudget.trim() && { lifetime_budget: Number(lifetimeBudget) }),
          ...(expiryDays.trim() && { expiry_days: Number(expiryDays) }),
        },
      })
      // Approve is contractually required to return a key. If it doesn't,
      // surface an error rather than silently closing the panel.
      if (result.key) {
        onProvisioned(result.key)
      } else {
        setError('Approved, but no key token was returned — contact your administrator.')
      }
    } catch {
      setError('Unable to approve request. Please try again.')
    }
  }

  return (
    <form className="form form--inline" onSubmit={handleSubmit}>
      <h3 className="form__title">
        Approve request — {request.cost_centre_code}
      </h3>

      <fieldset className="approve-panel__fieldset">
        <legend className="approve-panel__legend">
          Allowed models
        </legend>
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
          />
        </label>
        <label className="form__field">
          <span>Key expiry (days from now)</span>
          <input
            type="number"
            min="1"
            step="1"
            value={expiryDays}
            onChange={(e) => setExpiryDays(e.target.value)}
            placeholder="Leave blank for none"
          />
        </label>
      </div>

      {error && (
        <p className="status status--error" role="alert">
          {error}
        </p>
      )}

      <div className="form__row">
        <button type="submit" disabled={approve.isPending}>
          {approve.isPending ? 'Approving…' : 'Approve'}
        </button>
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function RejectPanel({
  request,
  onDone,
}: {
  request: KeyRequest
  onDone: () => void
}) {
  const reject = useRejectKeyRequest()
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      await reject.mutateAsync({
        id: request.id,
        input: { rejection_reason: reason.trim() },
      })
      onDone()
    } catch {
      setError('Unable to reject request. Please try again.')
    }
  }

  return (
    <form className="form form--inline" onSubmit={handleSubmit}>
      <h3 className="form__title">
        Reject request — {request.cost_centre_code}
      </h3>
      <label className="form__field">
        <span>Rejection reason</span>
        <textarea
          aria-label="Rejection reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          required
        />
      </label>
      {error && (
        <p className="status status--error" role="alert">
          {error}
        </p>
      )}
      <div className="form__row">
        <button type="submit" disabled={reject.isPending || !reason.trim()}>
          {reject.isPending ? 'Rejecting…' : 'Reject'}
        </button>
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  )
}
