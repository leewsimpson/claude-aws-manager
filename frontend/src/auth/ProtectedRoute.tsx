import { Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from './AuthContext'
import { roleHome } from './roleHome'

// Gates protected routes. While a stored session is being validated we show a
// lightweight loader rather than bouncing to /login (which would flash).
// Pass `requireRoles` to additionally gate a route by role: a signed-in user
// who holds none of them is sent to their own role home instead of seeing a
// page they can't use (the backend also enforces this server-side).
export function ProtectedRoute({
  children,
  requireRoles,
}: {
  children: ReactNode
  requireRoles?: string[]
}) {
  const { status, roles } = useAuth()

  if (status === 'restoring') {
    return (
      <main className="page">
        <p className="status status--loading">Loading…</p>
      </main>
    )
  }

  if (status === 'unauthenticated') {
    return <Navigate to="/login" replace />
  }

  if (requireRoles && !requireRoles.some((role) => roles.includes(role))) {
    return <Navigate to={roleHome(roles)} replace />
  }

  return <>{children}</>
}
