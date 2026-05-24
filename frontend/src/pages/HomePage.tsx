import { useAuth } from '../auth/AuthContext'

export function HomePage() {
  const { user, roles } = useAuth()

  if (!user) return null

  return (
    <section className="panel">
      <h1>Welcome, {user.display_name}</h1>
      <p>
        Signed in as <strong>{user.username}</strong>.
      </p>
      <p className="roles">
        Roles: {roles.length > 0 ? roles.join(', ') : 'none'}
      </p>
      <p>
        Use the navigation above to manage cost centres and Claude Code access.
      </p>
    </section>
  )
}
