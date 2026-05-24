import { http, HttpResponse } from 'msw'
import type {
  CostCentre,
  UserListItem,
} from '../features/costCentres/types'

export const TEST_TOKEN = 'test-token-123'
export const ADMIN_TOKEN = 'admin-token-456'

export const TEST_USER = {
  id: 1,
  username: 'dev1',
  display_name: 'Developer One',
  email: 'dev1@example.com',
  roles: ['developer'],
}

export const ADMIN_USER = {
  id: 2,
  username: 'admin',
  display_name: 'Administrator',
  email: 'admin@example.com',
  roles: ['admin'],
}

// Users available for the owner picker.
const USERS: UserListItem[] = [
  {
    id: 'u-dev1',
    username: 'dev1',
    display_name: 'Developer One',
    email: 'dev1@example.com',
    roles: ['developer'],
    is_active: true,
  },
  {
    id: 'u-dev2',
    username: 'dev2',
    display_name: 'Developer Two',
    email: 'dev2@example.com',
    roles: ['developer'],
    is_active: true,
  },
  {
    id: 'u-ccowner1',
    username: 'ccowner1',
    display_name: 'Cost Centre Owner One',
    email: 'ccowner1@example.com',
    roles: ['cco', 'developer'],
    is_active: true,
  },
]

// Mutable in-memory store so create/archive/owner mutations are reflected by
// subsequent GETs within a test. Reset via resetCostCentreStore().
let nextId = 1
let costCentres: CostCentre[] = []

function seed(): CostCentre[] {
  return [
    {
      id: 'cc-1',
      code: 'ENG',
      name: 'Engineering',
      description: 'Engineering teams',
      status: 'active',
      budget_cap: 5000,
      created_by: 'u-admin',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      owners: [
        {
          user_id: 'u-ccowner1',
          username: 'ccowner1',
          display_name: 'Cost Centre Owner One',
          assigned_at: '2026-01-01T00:00:00Z',
        },
      ],
    },
    {
      id: 'cc-2',
      code: 'DATA',
      name: 'Data Science',
      description: null,
      status: 'active',
      budget_cap: null,
      created_by: 'u-admin',
      created_at: '2026-01-02T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
      owners: [],
    },
  ]
}

export function resetCostCentreStore() {
  nextId = 100
  costCentres = seed()
}
resetCostCentreStore()

function isAdmin(request: Request): boolean {
  return request.headers.get('Authorization') === `Bearer ${ADMIN_TOKEN}`
}

function isAuthed(request: Request): boolean {
  const auth = request.headers.get('Authorization')
  return auth === `Bearer ${TEST_TOKEN}` || auth === `Bearer ${ADMIN_TOKEN}`
}

const unauthorised = () =>
  HttpResponse.json({ detail: 'Not authenticated' }, { status: 401 })

const forbidden = () =>
  HttpResponse.json({ detail: 'Forbidden' }, { status: 403 })

export const handlers = [
  http.post('/api/auth/login', async ({ request }) => {
    const { username, password } = (await request.json()) as {
      username: string
      password: string
    }
    if (username === 'dev1' && password === 'dev1') {
      return HttpResponse.json({
        access_token: TEST_TOKEN,
        token_type: 'bearer',
        user: TEST_USER,
      })
    }
    if (username === 'admin' && password === 'admin') {
      return HttpResponse.json({
        access_token: ADMIN_TOKEN,
        token_type: 'bearer',
        user: ADMIN_USER,
      })
    }
    return HttpResponse.json({ detail: 'Invalid credentials' }, { status: 401 })
  }),

  http.get('/api/auth/me', ({ request }) => {
    const auth = request.headers.get('Authorization')
    if (auth === `Bearer ${TEST_TOKEN}`) {
      return HttpResponse.json({ ...TEST_USER, is_active: true })
    }
    if (auth === `Bearer ${ADMIN_TOKEN}`) {
      return HttpResponse.json({ ...ADMIN_USER, is_active: true })
    }
    return unauthorised()
  }),

  http.get('/api/users', ({ request }) => {
    if (!isAuthed(request)) return unauthorised()
    if (!isAdmin(request)) return forbidden()
    return HttpResponse.json(USERS)
  }),

  http.get('/api/cost-centres', ({ request }) => {
    if (!isAuthed(request)) return unauthorised()
    // Admins see all; developers only active ones (backend scopes this).
    const visible = isAdmin(request)
      ? costCentres
      : costCentres.filter((cc) => cc.status === 'active')
    return HttpResponse.json(visible)
  }),

  http.get('/api/cost-centres/:id', ({ request, params }) => {
    if (!isAuthed(request)) return unauthorised()
    const cc = costCentres.find((c) => c.id === params.id)
    if (!cc) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    return HttpResponse.json(cc)
  }),

  http.post('/api/cost-centres', async ({ request }) => {
    if (!isAuthed(request)) return unauthorised()
    if (!isAdmin(request)) return forbidden()
    const body = (await request.json()) as {
      code: string
      name: string
      description?: string
      budget_cap?: number | null
    }
    if (costCentres.some((c) => c.code === body.code)) {
      return HttpResponse.json(
        { detail: 'code already exists' },
        { status: 409 },
      )
    }
    const now = new Date().toISOString()
    const created: CostCentre = {
      id: `cc-${nextId++}`,
      code: body.code,
      name: body.name,
      description: body.description ?? null,
      status: 'active',
      budget_cap: body.budget_cap ?? null,
      created_by: 'u-admin',
      created_at: now,
      updated_at: now,
      owners: [],
    }
    costCentres = [...costCentres, created]
    return HttpResponse.json(created, { status: 201 })
  }),

  http.patch('/api/cost-centres/:id', async ({ request, params }) => {
    if (!isAuthed(request)) return unauthorised()
    if (!isAdmin(request)) return forbidden()
    const cc = costCentres.find((c) => c.id === params.id)
    if (!cc) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const body = (await request.json()) as {
      name?: string
      description?: string | null
      budget_cap?: number | null
    }
    if (body.name !== undefined) cc.name = body.name
    if (body.description !== undefined) cc.description = body.description
    if (body.budget_cap !== undefined) cc.budget_cap = body.budget_cap
    cc.updated_at = new Date().toISOString()
    return HttpResponse.json(cc)
  }),

  http.post('/api/cost-centres/:id/archive', ({ request, params }) => {
    if (!isAuthed(request)) return unauthorised()
    if (!isAdmin(request)) return forbidden()
    const cc = costCentres.find((c) => c.id === params.id)
    if (!cc) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    cc.status = 'archived'
    cc.updated_at = new Date().toISOString()
    return HttpResponse.json(cc)
  }),

  http.post('/api/cost-centres/:id/unarchive', ({ request, params }) => {
    if (!isAuthed(request)) return unauthorised()
    if (!isAdmin(request)) return forbidden()
    const cc = costCentres.find((c) => c.id === params.id)
    if (!cc) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    cc.status = 'active'
    cc.updated_at = new Date().toISOString()
    return HttpResponse.json(cc)
  }),

  http.post('/api/cost-centres/:id/owners', async ({ request, params }) => {
    if (!isAuthed(request)) return unauthorised()
    if (!isAdmin(request)) return forbidden()
    const cc = costCentres.find((c) => c.id === params.id)
    if (!cc) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const { user_id } = (await request.json()) as { user_id: string }
    if (cc.owners.some((o) => o.user_id === user_id)) {
      return HttpResponse.json({ detail: 'already owner' }, { status: 409 })
    }
    const user = USERS.find((u) => u.id === user_id)
    if (!user) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    cc.owners = [
      ...cc.owners,
      {
        user_id: user.id,
        username: user.username,
        display_name: user.display_name,
        assigned_at: new Date().toISOString(),
      },
    ]
    return HttpResponse.json(cc)
  }),

  http.delete('/api/cost-centres/:id/owners/:userId', ({ request, params }) => {
    if (!isAuthed(request)) return unauthorised()
    if (!isAdmin(request)) return forbidden()
    const cc = costCentres.find((c) => c.id === params.id)
    if (!cc) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    cc.owners = cc.owners.filter((o) => o.user_id !== params.userId)
    return HttpResponse.json(cc)
  }),
]
