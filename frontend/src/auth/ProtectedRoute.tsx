import { Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from './AuthContext'

// Gates protected routes. While a stored session is being validated we show a
// lightweight loader rather than bouncing to /login (which would flash).
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { status } = useAuth()

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

  return <>{children}</>
}
