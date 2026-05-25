import { useState, type FormEvent } from 'react'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../lib/api'
import {
  useArchiveCostCentre,
  useAssignOwner,
  useCostCentres,
  useCreateCostCentre,
  useRemoveOwner,
  useUnarchiveCostCentre,
  useUpdateCostCentre,
  useUpdateCcDefaults,
  useUsers,
} from '../features/costCentres/api'
import type { CostCentre, RequestDefaults } from '../features/costCentres/types'

function formatBudget(value: number | null): string {
  if (value === null || value === undefined) return '—'
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: 'AUD',
    maximumFractionDigits: 0,
  }).format(value)
}

export function CostCentresPage() {
  const { user, hasRole } = useAuth()
  const isAdmin = hasRole('admin')
  const isCco = hasRole('cco')
  const { data, isLoading, isError } = useCostCentres()

  return (
    <section className="panel panel--wide">
      <div className="panel__header">
        <h1>Cost centres</h1>
      </div>

      {isAdmin && <CreateCostCentreForm />}

      {isLoading && (
        <p className="status status--loading">Loading cost centres…</p>
      )}
      {isError && (
        <p className="status status--error" role="alert">
          Unable to load cost centres.
        </p>
      )}
      {data && data.length === 0 && (
        <p className="status">No cost centres yet.</p>
      )}

      {data && data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Status</th>
              <th>Budget cap</th>
              <th>Owners</th>
              {(isAdmin || isCco) && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {data.map((cc) => {
              const isCcoOfThis = cc.owners.some(
                (o) => String(o.user_id) === String(user?.id),
              )
              return (
                <CostCentreRow
                  key={cc.id}
                  costCentre={cc}
                  isAdmin={isAdmin}
                  isCco={isCcoOfThis}
                />
              )
            })}
          </tbody>
        </table>
      )}
    </section>
  )
}

function CreateCostCentreForm() {
  const create = useCreateCostCentre()
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [budgetCap, setBudgetCap] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      await create.mutateAsync({
        code: code.trim(),
        name: name.trim(),
        description: description.trim() || undefined,
        budget_cap: budgetCap.trim() ? Number(budgetCap) : undefined,
      })
      setCode('')
      setName('')
      setDescription('')
      setBudgetCap('')
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('A cost centre with that code already exists.')
      } else {
        setError('Unable to create cost centre. Please try again.')
      }
    }
  }

  return (
    <form className="form form--inline" onSubmit={handleSubmit}>
      <h2 className="form__title">New cost centre</h2>
      <div className="form__row">
        <label className="form__field">
          <span>Code</span>
          <input
            name="code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
          />
        </label>
        <label className="form__field">
          <span>Name</span>
          <input
            name="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </label>
        <label className="form__field">
          <span>Budget cap</span>
          <input
            name="budget_cap"
            type="number"
            min="0"
            step="1"
            value={budgetCap}
            onChange={(e) => setBudgetCap(e.target.value)}
          />
        </label>
      </div>
      <label className="form__field">
        <span>Description</span>
        <input
          name="description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </label>
      {error && (
        <p className="status status--error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" disabled={create.isPending}>
        {create.isPending ? 'Creating…' : 'Create cost centre'}
      </button>
    </form>
  )
}

function CostCentreRow({
  costCentre,
  isAdmin,
  isCco,
}: {
  costCentre: CostCentre
  isAdmin: boolean
  isCco: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [managingOwners, setManagingOwners] = useState(false)
  const [managingDefaults, setManagingDefaults] = useState(false)
  const archive = useArchiveCostCentre()
  const unarchive = useUnarchiveCostCentre()

  const ownerNames =
    costCentre.owners.length > 0
      ? costCentre.owners.map((o) => o.username).join(', ')
      : '—'

  const canManageDefaults = isAdmin || isCco

  return (
    <>
      <tr>
        <td>{costCentre.code}</td>
        <td>{costCentre.name}</td>
        <td>
          <span className={`badge badge--${costCentre.status}`}>
            {costCentre.status}
          </span>
        </td>
        <td>{formatBudget(costCentre.budget_cap)}</td>
        <td>{ownerNames}</td>
        {(isAdmin || isCco) && (
          <td className="table__actions">
            {canManageDefaults && (
              <button
                type="button"
                className="btn btn--small"
                onClick={() => setManagingDefaults((v) => !v)}
              >
                {managingDefaults ? 'Close' : 'Defaults'}
              </button>
            )}
            {isAdmin && (
              <>
                <button
                  type="button"
                  className="btn btn--small"
                  onClick={() => setEditing((v) => !v)}
                >
                  {editing ? 'Close' : 'Edit'}
                </button>
                <button
                  type="button"
                  className="btn btn--small"
                  onClick={() => setManagingOwners((v) => !v)}
                >
                  Owners
                </button>
                {costCentre.status === 'active' ? (
                  <button
                    type="button"
                    className="btn btn--small btn--danger"
                    disabled={archive.isPending}
                    onClick={() => archive.mutate(costCentre.id)}
                  >
                    Archive
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn btn--small"
                    disabled={unarchive.isPending}
                    onClick={() => unarchive.mutate(costCentre.id)}
                  >
                    Unarchive
                  </button>
                )}
              </>
            )}
          </td>
        )}
      </tr>
      {managingDefaults && (
        <tr>
          <td colSpan={6}>
            <DefaultsPanel
              costCentre={costCentre}
              onDone={() => setManagingDefaults(false)}
            />
          </td>
        </tr>
      )}
      {isAdmin && editing && (
        <tr>
          <td colSpan={6}>
            <EditCostCentreForm
              costCentre={costCentre}
              onDone={() => setEditing(false)}
            />
          </td>
        </tr>
      )}
      {isAdmin && managingOwners && (
        <tr>
          <td colSpan={6}>
            <OwnersPanel costCentre={costCentre} />
          </td>
        </tr>
      )}
    </>
  )
}

function EditCostCentreForm({
  costCentre,
  onDone,
}: {
  costCentre: CostCentre
  onDone: () => void
}) {
  const update = useUpdateCostCentre()
  const [name, setName] = useState(costCentre.name)
  const [description, setDescription] = useState(costCentre.description ?? '')
  const [budgetCap, setBudgetCap] = useState(
    costCentre.budget_cap === null ? '' : String(costCentre.budget_cap),
  )
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      await update.mutateAsync({
        id: costCentre.id,
        input: {
          name: name.trim(),
          description: description.trim() || null,
          budget_cap: budgetCap.trim() ? Number(budgetCap) : null,
        },
      })
      onDone()
    } catch {
      setError('Unable to save changes.')
    }
  }

  return (
    <form className="form form--inline" onSubmit={handleSubmit}>
      <div className="form__row">
        <label className="form__field">
          <span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label className="form__field">
          <span>Budget cap</span>
          <input
            type="number"
            min="0"
            step="1"
            value={budgetCap}
            onChange={(e) => setBudgetCap(e.target.value)}
          />
        </label>
      </div>
      <label className="form__field">
        <span>Description</span>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </label>
      {error && (
        <p className="status status--error" role="alert">
          {error}
        </p>
      )}
      <div className="form__row">
        <button type="submit" disabled={update.isPending}>
          {update.isPending ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function OwnersPanel({ costCentre }: { costCentre: CostCentre }) {
  const { data: users } = useUsers()
  const assign = useAssignOwner()
  const remove = useRemoveOwner()
  const [selected, setSelected] = useState('')

  const ownerIds = new Set(costCentre.owners.map((o) => o.user_id))
  const candidates = (users ?? []).filter((u) => !ownerIds.has(u.id))

  return (
    <div className="owners">
      <h3 className="owners__title">Owners of {costCentre.code}</h3>
      <ul className="owners__list">
        {costCentre.owners.length === 0 && <li>No owners assigned.</li>}
        {costCentre.owners.map((o) => (
          <li key={o.user_id}>
            {o.display_name} ({o.username})
            <button
              type="button"
              className="btn btn--small btn--danger"
              disabled={remove.isPending}
              onClick={() =>
                remove.mutate({ id: costCentre.id, userId: o.user_id })
              }
            >
              Remove
            </button>
          </li>
        ))}
      </ul>
      <div className="form__row">
        <label className="form__field">
          <span>Add owner</span>
          <select
            aria-label={`Add owner to ${costCentre.code}`}
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value="">Select a user…</option>
            {candidates.map((u) => (
              <option key={u.id} value={u.id}>
                {u.display_name} ({u.username})
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="btn"
          disabled={!selected || assign.isPending}
          onClick={() => {
            if (!selected) return
            assign.mutate(
              { id: costCentre.id, userId: selected },
              { onSuccess: () => setSelected('') },
            )
          }}
        >
          Assign
        </button>
      </div>
    </div>
  )
}

const DEFAULT_MODEL_OPTIONS = [
  'anthropic.claude-sonnet-4-6',
  'anthropic.claude-haiku-4-5',
]

function toDateInputValue(iso: string | null | undefined): string {
  if (!iso) return ''
  return iso.slice(0, 10)
}

function DefaultsPanel({
  costCentre,
  onDone,
}: {
  costCentre: CostCentre
  onDone: () => void
}) {
  const updateDefaults = useUpdateCcDefaults()
  const defaults = costCentre.request_defaults

  const [selectedModels, setSelectedModels] = useState<Set<string>>(
    new Set(defaults?.allowed_models ?? DEFAULT_MODEL_OPTIONS),
  )
  const [rollingLimit, setRollingLimit] = useState(
    defaults?.rolling_limit != null ? String(defaults.rolling_limit) : '',
  )
  const [rollingPeriodDays, setRollingPeriodDays] = useState(
    defaults?.rolling_period_days != null
      ? String(defaults.rolling_period_days)
      : '',
  )
  const [lifetimeBudget, setLifetimeBudget] = useState(
    defaults?.lifetime_budget != null ? String(defaults.lifetime_budget) : '',
  )
  const [expiresAt, setExpiresAt] = useState(
    toDateInputValue(defaults?.expires_at),
  )
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

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
    setSuccess(false)
    try {
      const input: RequestDefaults = {}
      if (selectedModels.size > 0) {
        input.allowed_models = Array.from(selectedModels)
      }
      if (rollingLimit.trim()) input.rolling_limit = Number(rollingLimit)
      if (rollingPeriodDays.trim())
        input.rolling_period_days = Number(rollingPeriodDays)
      if (lifetimeBudget.trim()) input.lifetime_budget = Number(lifetimeBudget)
      if (expiresAt.trim()) {
        input.expires_at = new Date(expiresAt + 'T23:59:59Z').toISOString()
      }
      await updateDefaults.mutateAsync({ id: costCentre.id, input })
      setSuccess(true)
    } catch {
      setError('Unable to save defaults.')
    }
  }

  return (
    <form className="form form--inline" onSubmit={handleSubmit}>
      <h3 className="form__title">
        Request defaults — {costCentre.code}
      </h3>

      <fieldset className="approve-panel__fieldset">
        <legend className="approve-panel__legend">Default allowed models</legend>
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
            placeholder="Global default"
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
            placeholder="Global default"
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
            placeholder="Global default"
          />
        </label>
        <label className="form__field">
          <span>Project end date</span>
          <input
            type="date"
            value={expiresAt}
            onChange={(e) => setExpiresAt(e.target.value)}
          />
        </label>
      </div>

      {error && (
        <p className="status status--error" role="alert">
          {error}
        </p>
      )}
      {success && (
        <p className="status status--ok">Defaults saved.</p>
      )}

      <div className="form__row">
        <button type="submit" disabled={updateDefaults.isPending}>
          {updateDefaults.isPending ? 'Saving…' : 'Save defaults'}
        </button>
        <button type="button" className="btn" onClick={onDone}>
          Close
        </button>
      </div>
    </form>
  )
}
