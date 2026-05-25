import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { roleHome } from '../auth/roleHome'

// The index route ("/") no longer renders a page of its own — it sends the
// signed-in user straight to the destination that matters most for their role.
// Rendered inside ProtectedRoute (so the user is always authenticated here) and
// without AppLayout, so there's no flash of nav chrome before the redirect.
export function HomeRedirect() {
  const { roles } = useAuth()
  return <Navigate to={roleHome(roles)} replace />
}
