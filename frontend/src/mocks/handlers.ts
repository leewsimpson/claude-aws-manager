import { http, HttpResponse } from 'msw'
import type {
  CostCentre,
  UserListItem,
} from '../features/costCentres/types'
import type {
  KeyRequest,
  KeyRequestResult,
  ProvisionedKey,
} from '../features/keyRequests/types'
import type { Key, KeyStatus } from '../features/keys/types'

export const TEST_TOKEN = 'test-token-123'
export const ADMIN_TOKEN = 'admin-token-456'
export const CCO_TOKEN = 'cco-token-789'

export const TEST_USER = {
  id: 'u-dev1',
  username: 'dev1',
  display_name: 'Developer One',
  email: 'dev1@example.com',
  roles: ['developer'],
}

export const ADMIN_USER = {
  id: 'u-admin',
  username: 'admin',
  display_name: 'Administrator',
  email: 'admin@example.com',
  roles: ['admin'],
}

export const CCO_USER = {
  id: 'u-ccowner1',
  username: 'ccowner1',
  display_name: 'Cost Centre Owner One',
  email: 'ccowner1@example.com',
  roles: ['cco', 'developer'],
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

function isCco(request: Request): boolean {
  return request.headers.get('Authorization') === `Bearer ${CCO_TOKEN}`
}

function isAuthed(request: Request): boolean {
  const auth = request.headers.get('Authorization')
  return (
    auth === `Bearer ${TEST_TOKEN}` ||
    auth === `Bearer ${ADMIN_TOKEN}` ||
    auth === `Bearer ${CCO_TOKEN}`
  )
}

function getRequestingUserId(request: Request): string {
  const auth = request.headers.get('Authorization')
  if (auth === `Bearer ${ADMIN_TOKEN}`) return ADMIN_USER.id
  if (auth === `Bearer ${CCO_TOKEN}`) return CCO_USER.id
  return TEST_USER.id
}

// ---- Key request store ----

let nextKeyRequestId = 1
let keyRequests: KeyRequest[] = []

function seedKeyRequests(): KeyRequest[] {
  return []
}

export function resetKeyRequestStore() {
  nextKeyRequestId = 1
  keyRequests = seedKeyRequests()
}
resetKeyRequestStore()

/** Directly inject a pending request into the store so reviewer tests don't
 *  need a two-render setup. Returns the seeded request. */
export function seedPendingKeyRequest(overrides?: Partial<KeyRequest>): KeyRequest {
  const cc = costCentres[0]!
  const id = `kr-seed-${nextKeyRequestId++}`
  const now = '2026-05-24T10:00:00Z'
  const req: KeyRequest = {
    id,
    developer_id: TEST_USER.id,
    developer_username: TEST_USER.username,
    developer_display_name: TEST_USER.display_name,
    cost_centre_id: cc.id,
    cost_centre_code: cc.code,
    cost_centre_name: cc.name,
    status: 'pending',
    justification: null,
    rejection_reason: null,
    reviewed_by: null,
    reviewed_at: null,
    approved_constraints: null,
    created_at: now,
    updated_at: now,
    ...overrides,
  }
  keyRequests = [...keyRequests, req]
  return req
}

function makeProvisionedKey(
  request: KeyRequest,
  allowedModels: string[],
  expiryDays?: number,
): ProvisionedKey {
  return {
    id: `key-${nextKeyRequestId}`,
    cost_centre_id: request.cost_centre_id,
    cost_centre_code: request.cost_centre_code,
    iam_username: `claude-${request.developer_username}-${request.cost_centre_code.toLowerCase()}`,
    status: 'active',
    allowed_models: allowedModels,
    rolling_limit: null,
    rolling_period_days: null,
    lifetime_budget: null,
    expires_at: expiryDays
      ? new Date(Date.now() + expiryDays * 86400000).toISOString()
      : null,
    bearer_token: `mock-bearer-token-${request.id}`,
    inference_profiles: allowedModels.map((m) => ({
      model_id: m,
      profile_arn: `arn:aws:bedrock:ap-southeast-2:123456789:inference-profile/${request.cost_centre_code.toLowerCase()}-${m.replace(/\./g, '-')}`,
      profile_name: `${request.cost_centre_code}-${m}`,
    })),
  }
}

// ---- Keys store ----

let nextKeyId = 1
let keys: Key[] = []

function seedKeys(): Key[] {
  return []
}

export function resetKeyStore() {
  nextKeyId = 1
  keys = seedKeys()
}
resetKeyStore()

/** Directly inject a key into the store so tests don't need a full flow.
 *  Returns the seeded key. */
export function seedKey(overrides?: Partial<Key>): Key {
  const cc = costCentres[0]!
  const id = `key-seed-${nextKeyId++}`
  const now = '2026-05-24T10:00:00Z'
  const defaultModels = ['anthropic.claude-sonnet-4-6', 'anthropic.claude-haiku-4-5']
  const key: Key = {
    id,
    developer_id: TEST_USER.id,
    developer_username: TEST_USER.username,
    developer_display_name: TEST_USER.display_name,
    cost_centre_id: cc.id,
    cost_centre_code: cc.code,
    cost_centre_name: cc.name,
    iam_username: `claude-${TEST_USER.username}-${cc.code.toLowerCase()}`,
    status: 'active',
    allowed_models: defaultModels,
    rolling_limit: null,
    rolling_period_days: null,
    lifetime_budget: null,
    lifetime_spend: 0,
    expires_at: null,
    created_at: now,
    revoked_at: null,
    inference_profiles: defaultModels.map((m) => ({
      model_id: m,
      profile_arn: `arn:aws:bedrock:ap-southeast-2:123456789:inference-profile/${cc.code.toLowerCase()}-${m.replace(/\./g, '-')}`,
      profile_name: `${cc.code}-${m}`,
    })),
    ...overrides,
  }
  keys = [...keys, key]
  return key
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
    if (username === 'ccowner1' && password === 'ccowner1') {
      return HttpResponse.json({
        access_token: CCO_TOKEN,
        token_type: 'bearer',
        user: CCO_USER,
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
    if (auth === `Bearer ${CCO_TOKEN}`) {
      return HttpResponse.json({ ...CCO_USER, is_active: true })
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

  // ---- Key requests ----

  http.get('/api/key-requests', ({ request }) => {
    if (!isAuthed(request)) return unauthorised()
    const url = new URL(request.url)
    const statusFilter = url.searchParams.get('status')
    const userId = getRequestingUserId(request)
    const isReviewer = isAdmin(request) || isCco(request)

    let visible = isReviewer
      ? keyRequests
      : keyRequests.filter((r) => r.developer_id === userId)

    if (statusFilter) {
      visible = visible.filter((r) => r.status === statusFilter)
    }
    return HttpResponse.json(visible)
  }),

  http.get('/api/key-requests/:id', ({ request, params }) => {
    if (!isAuthed(request)) return unauthorised()
    const req = keyRequests.find((r) => r.id === params.id)
    if (!req) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    return HttpResponse.json(req)
  }),

  http.post('/api/key-requests', async ({ request }) => {
    if (!isAuthed(request)) return unauthorised()
    const body = (await request.json()) as {
      cost_centre_id: string
      justification?: string
    }
    const userId = getRequestingUserId(request)
    const isCcoUser = isCco(request)
    const userObj = isCco(request) ? CCO_USER : isAdmin(request) ? ADMIN_USER : TEST_USER

    const cc = costCentres.find((c) => c.id === body.cost_centre_id)
    if (!cc) return HttpResponse.json({ detail: 'Cost centre not found' }, { status: 404 })

    // Conflict: already an active/pending request for this developer + cc
    const existing = keyRequests.find(
      (r) =>
        r.developer_id === userId &&
        r.cost_centre_id === body.cost_centre_id &&
        (r.status === 'pending' || r.status === 'approved'),
    )
    if (existing) {
      return HttpResponse.json(
        { detail: 'Active or pending request already exists' },
        { status: 409 },
      )
    }

    const id = `kr-${nextKeyRequestId++}`
    const now = new Date().toISOString()
    // CCO auto-approve own requests
    const autoApprove = isCcoUser && cc.owners.some((o) => o.user_id === userId)
    const newRequest: KeyRequest = {
      id,
      developer_id: userId,
      developer_username: userObj.username,
      developer_display_name: userObj.display_name,
      cost_centre_id: cc.id,
      cost_centre_code: cc.code,
      cost_centre_name: cc.name,
      status: autoApprove ? 'approved' : 'pending',
      justification: body.justification ?? null,
      rejection_reason: null,
      reviewed_by: autoApprove ? userId : null,
      reviewed_at: autoApprove ? now : null,
      approved_constraints: autoApprove
        ? { allowed_models: ['anthropic.claude-sonnet-4-6', 'anthropic.claude-haiku-4-5'], rolling_limit: null, rolling_period_days: null, lifetime_budget: null, expiry_days: null }
        : null,
      created_at: now,
      updated_at: now,
    }
    keyRequests = [...keyRequests, newRequest]

    const result: KeyRequestResult = {
      request: newRequest,
      key: autoApprove ? makeProvisionedKey(newRequest, ['anthropic.claude-sonnet-4-6', 'anthropic.claude-haiku-4-5']) : null,
    }
    return HttpResponse.json(result, { status: 201 })
  }),

  http.post('/api/key-requests/:id/approve', async ({ request, params }) => {
    if (!isAuthed(request)) return unauthorised()
    if (!isAdmin(request) && !isCco(request)) return forbidden()
    const req = keyRequests.find((r) => r.id === params.id)
    if (!req) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const body = (await request.json()) as {
      allowed_models?: string[]
      rolling_limit?: number
      rolling_period_days?: number
      lifetime_budget?: number
      expiry_days?: number
    }
    const reviewerId = getRequestingUserId(request)
    const now = new Date().toISOString()
    const allowedModels = body.allowed_models ?? ['anthropic.claude-sonnet-4-6', 'anthropic.claude-haiku-4-5']

    req.status = 'approved'
    req.reviewed_by = reviewerId
    req.reviewed_at = now
    req.approved_constraints = {
      allowed_models: allowedModels,
      rolling_limit: body.rolling_limit ?? null,
      rolling_period_days: body.rolling_period_days ?? null,
      lifetime_budget: body.lifetime_budget ?? null,
      expiry_days: body.expiry_days ?? null,
    }
    req.updated_at = now

    const key = makeProvisionedKey(req, allowedModels, body.expiry_days)
    const result: KeyRequestResult = { request: req, key }
    return HttpResponse.json(result)
  }),

  http.post('/api/key-requests/:id/reject', async ({ request, params }) => {
    if (!isAuthed(request)) return unauthorised()
    if (!isAdmin(request) && !isCco(request)) return forbidden()
    const req = keyRequests.find((r) => r.id === params.id)
    if (!req) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const body = (await request.json()) as { rejection_reason: string }
    const reviewerId = getRequestingUserId(request)
    const now = new Date().toISOString()

    req.status = 'rejected'
    req.reviewed_by = reviewerId
    req.reviewed_at = now
    req.rejection_reason = body.rejection_reason
    req.updated_at = now

    const result: KeyRequestResult = { request: req, key: null }
    return HttpResponse.json(result)
  }),

  // ---- Keys ----

  http.get('/api/keys', ({ request }) => {
    if (!isAuthed(request)) return unauthorised()
    const url = new URL(request.url)
    const statusFilter = url.searchParams.get('status') as KeyStatus | null
    const ccFilter = url.searchParams.get('cost_centre_id')
    const developerFilter = url.searchParams.get('developer_id')

    const userId = getRequestingUserId(request)
    const isReviewer = isAdmin(request) || isCco(request)

    let visible = isReviewer
      ? keys
      : keys.filter((k) => k.developer_id === userId)

    if (statusFilter) visible = visible.filter((k) => k.status === statusFilter)
    if (ccFilter) visible = visible.filter((k) => k.cost_centre_id === ccFilter)
    if (developerFilter) visible = visible.filter((k) => k.developer_id === developerFilter)

    return HttpResponse.json(visible)
  }),

  http.get('/api/keys/:id', ({ request, params }) => {
    if (!isAuthed(request)) return unauthorised()
    const key = keys.find((k) => k.id === params.id)
    if (!key) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    return HttpResponse.json(key)
  }),

  http.post('/api/keys/:id/revoke', ({ request, params }) => {
    if (!isAuthed(request)) return unauthorised()
    const key = keys.find((k) => k.id === params.id)
    if (!key) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const userId = getRequestingUserId(request)
    const isReviewer = isAdmin(request) || isCco(request)
    // Only the owner or a reviewer can revoke
    if (!isReviewer && key.developer_id !== userId) return forbidden()
    key.status = 'revoked'
    key.revoked_at = new Date().toISOString()
    return HttpResponse.json(key)
  }),

  http.post('/api/keys/:id/regenerate', ({ request, params }) => {
    if (!isAuthed(request)) return unauthorised()
    const key = keys.find((k) => k.id === params.id)
    if (!key) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const userId = getRequestingUserId(request)
    // Only the key owner can regenerate
    if (key.developer_id !== userId) return forbidden()
    const provisioned: ProvisionedKey = {
      id: key.id,
      cost_centre_id: key.cost_centre_id,
      cost_centre_code: key.cost_centre_code,
      iam_username: key.iam_username,
      status: key.status,
      allowed_models: key.allowed_models,
      rolling_limit: key.rolling_limit,
      rolling_period_days: key.rolling_period_days,
      lifetime_budget: key.lifetime_budget,
      expires_at: key.expires_at,
      bearer_token: `mock-regen-bearer-${key.id}`,
      inference_profiles: key.inference_profiles,
    }
    return HttpResponse.json(provisioned)
  }),

  http.patch('/api/keys/:id/constraints', async ({ request, params }) => {
    if (!isAuthed(request)) return unauthorised()
    if (!isAdmin(request) && !isCco(request)) return forbidden()
    const key = keys.find((k) => k.id === params.id)
    if (!key) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const body = (await request.json()) as {
      allowed_models?: string[]
      rolling_limit?: number | null
      rolling_period_days?: number | null
      lifetime_budget?: number | null
      expiry_days?: number | null
    }
    if (body.allowed_models !== undefined) key.allowed_models = body.allowed_models
    if (body.rolling_limit !== undefined) key.rolling_limit = body.rolling_limit
    if (body.rolling_period_days !== undefined) key.rolling_period_days = body.rolling_period_days
    if (body.lifetime_budget !== undefined) key.lifetime_budget = body.lifetime_budget
    if (body.expiry_days !== undefined && body.expiry_days !== null) {
      key.expires_at = new Date(Date.now() + body.expiry_days * 86400000).toISOString()
    }
    return HttpResponse.json(key)
  }),
]
