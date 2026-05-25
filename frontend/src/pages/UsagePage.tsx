import { AdminUsageSummary } from '../features/usage/components'

// Admin landing page: organisation-wide spend overview. Route is gated to the
// admin role (see App.tsx / ProtectedRoute), so non-admins never reach it.
export function UsagePage() {
  return (
    <section className="panel panel--wide">
      <div className="panel__header">
        <h1>Organisation usage</h1>
      </div>
      <AdminUsageSummary />
    </section>
  )
}
