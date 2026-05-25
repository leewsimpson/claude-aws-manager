import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../lib/api'
import { TEST_MODE, TEST_PERSONAS, type TestPersona } from '../config'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  // Return the user to where they were heading, defaulting to home.
  const from = (location.state as { from?: string } | null)?.from ?? '/'

  async function signIn(user: string, pass: string) {
    setError(null)
    setPending(true)
    try {
      await login(user, pass)
      navigate(from, { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError('Incorrect username or password.')
      } else {
        setError('Unable to sign in. Please try again.')
      }
    } finally {
      setPending(false)
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    void signIn(username, password)
  }

  function handlePersona(persona: TestPersona) {
    setUsername(persona.username)
    setPassword(persona.password)
    void signIn(persona.username, persona.password)
  }

  return (
    <main className="page">
      <section className="card">
        <h1>Claude Code AWS Bedrock Manager</h1>
        <form className="form" onSubmit={handleSubmit}>
          <label className="form__field">
            <span>Username</span>
            <input
              name="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </label>
          <label className="form__field">
            <span>Password</span>
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && (
            <p className="status status--error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" disabled={pending}>
            {pending ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        {TEST_MODE && (
          <section className="personas" aria-label="Test mode quick login">
            <p className="personas__label">// TEST MODE — quick login</p>
            <ul className="personas__list">
              {TEST_PERSONAS.map((persona) => (
                <li key={persona.username}>
                  <button
                    type="button"
                    className="btn personas__btn"
                    disabled={pending}
                    onClick={() => handlePersona(persona)}
                  >
                    <span className="personas__name">{persona.displayName}</span>
                    <span className="personas__meta">
                      {persona.username} · {persona.roles.join(', ')}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </section>
    </main>
  )
}
