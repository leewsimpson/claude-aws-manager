/**
 * App configuration.
 *
 * Test mode is a PoC/demo convenience: when enabled, the login page lists the
 * seeded personas as one-click sign-in buttons. It is driven by the Vite env
 * var `VITE_TEST_MODE` (see `.env.example`) so it stays OFF by default and in
 * production builds — set `VITE_TEST_MODE=true` in a `.env` / `.env.local` to
 * turn it on.
 */

export const TEST_MODE = import.meta.env.VITE_TEST_MODE === 'true'

export interface TestPersona {
  username: string
  /** PoC seed convention: password equals the username. */
  password: string
  displayName: string
  roles: string[]
}

/** Mirrors the backend seed in `backend/app/seed.py` (`_USERS`). */
export const TEST_PERSONAS: TestPersona[] = [
  { username: 'admin', password: 'admin', displayName: 'Admin User', roles: ['admin'] },
  { username: 'dev1', password: 'dev1', displayName: 'Developer One', roles: ['developer'] },
  { username: 'dev2', password: 'dev2', displayName: 'Developer Two', roles: ['developer'] },
  {
    username: 'ccowner1',
    password: 'ccowner1',
    displayName: 'Cost Centre Owner One',
    roles: ['cco', 'developer'],
  },
]
