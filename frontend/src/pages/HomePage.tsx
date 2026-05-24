import { useAuth } from '../auth/AuthContext'

export function HomePage() {
  const { user, roles, logout } = useAuth()

  if (!user) return null

  return (
    <main className="page">
      <section className="card">
        <h1>Claude Code AWS Bedrock Manager</h1>
        <p>
          Signed in as {user.display_name} ({user.username})
        </p>
        <p className="roles">
          Roles: {roles.length > 0 ? roles.join(', ') : 'none'}
        </p>
        <button type="button" onClick={logout}>
          Log out
        </button>
      </section>
    </main>
  )
}
