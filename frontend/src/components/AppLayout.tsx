import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

// Primary nav links. `roles` undefined = visible to every authenticated user;
// otherwise the link shows only if the user holds one of the listed roles.
// Order matches role precedence so each role's home sits first in its menu.
const NAV_LINKS: { to: string; label: string; roles?: string[] }[] = [
  { to: '/usage', label: 'Usage', roles: ['admin'] },
  { to: '/cost-centres', label: 'Cost centres', roles: ['admin', 'cco'] },
  { to: '/key-requests', label: 'Key requests' },
  { to: '/keys', label: 'Keys' },
]

// Shared chrome for authenticated pages: top nav with the app name, the links
// relevant to the signed-in user's role(s), and the user + logout. Pages render
// their content inside a wide container (vs. the centred card used for login).
export function AppLayout({ children }: { children: ReactNode }) {
  const { user, roles, logout } = useAuth()

  const links = NAV_LINKS.filter(
    (link) => !link.roles || link.roles.some((role) => roles.includes(role)),
  )

  return (
    <div className="layout">
      <header className="nav">
        <div className="nav__brand">Claude Code AWS Bedrock Manager</div>
        <nav className="nav__links">
          {links.map((link) => (
            <NavLink key={link.to} to={link.to} className="nav__link">
              {link.label}
            </NavLink>
          ))}
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
