import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

// Shared chrome for authenticated pages: top nav with the app name, primary
// links, and the signed-in user + logout. Pages render their content inside a
// wide container (vs. the centred card used for login).
export function AppLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()

  return (
    <div className="layout">
      <header className="nav">
        <div className="nav__brand">Claude Code AWS Bedrock Manager</div>
        <nav className="nav__links">
          <NavLink to="/" end className="nav__link">
            Home
          </NavLink>
          <NavLink to="/cost-centres" className="nav__link">
            Cost centres
          </NavLink>
          <NavLink to="/key-requests" className="nav__link">
            Key requests
          </NavLink>
        </nav>
        <div className="nav__user">
          {user && (
            <span className="nav__username">
              {user.display_name} ({user.username})
            </span>
          )}
          <button type="button" className="nav__logout" onClick={logout}>
            Log out
          </button>
        </div>
      </header>
      <main className="page page--wide">{children}</main>
    </div>
  )
}
