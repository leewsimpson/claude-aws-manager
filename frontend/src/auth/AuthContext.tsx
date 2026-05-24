import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, ApiError } from '../lib/api'

const TOKEN_KEY = 'cam.token'

export interface User {
  id: number | string
  username: string
  display_name: string
  email: string
  roles: string[]
}

interface LoginResponse {
  access_token: string
  token_type: string
  user: User
}

// 'restoring' = checking a stored token on mount; the app should not flash the
// login page until this resolves.
type AuthStatus = 'restoring' | 'authenticated' | 'unauthenticated'

interface AuthContextValue {
  user: User | null
  token: string | null
  status: AuthStatus
  roles: string[]
  hasRole: (role: string) => boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem(TOKEN_KEY),
  )
  const [user, setUser] = useState<User | null>(null)
  const [status, setStatus] = useState<AuthStatus>(() =>
    localStorage.getItem(TOKEN_KEY) ? 'restoring' : 'unauthenticated',
  )

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
    setStatus('unauthenticated')
  }, [])

  // On mount, validate any stored token via /auth/me and restore the session.
  useEffect(() => {
    const stored = localStorage.getItem(TOKEN_KEY)
    if (!stored) return

    let cancelled = false
    void (async () => {
      try {
        const me = await api<User & { is_active: boolean }>('/auth/me', {
          token: stored,
        })
        if (!cancelled) {
          setUser(me)
          setStatus('authenticated')
        }
      } catch (err) {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 401) {
          logout()
        } else {
          // Network/other error: drop the unverified session rather than hang.
          logout()
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [logout])

  const login = useCallback(async (username: string, password: string) => {
    const res = await api<LoginResponse>('/auth/login', {
      method: 'POST',
      body: { username, password },
    })
    localStorage.setItem(TOKEN_KEY, res.access_token)
    setToken(res.access_token)
    setUser(res.user)
    setStatus('authenticated')
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      status,
      roles: user?.roles ?? [],
      hasRole: (role: string) => user?.roles.includes(role) ?? false,
      login,
      logout,
    }),
    [user, token, status, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
