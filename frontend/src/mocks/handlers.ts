import { http, HttpResponse } from 'msw'

export const TEST_TOKEN = 'test-token-123'

export const TEST_USER = {
  id: 1,
  username: 'dev1',
  display_name: 'Developer One',
  email: 'dev1@example.com',
  roles: ['developer'],
}

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
    return HttpResponse.json({ detail: 'Invalid credentials' }, { status: 401 })
  }),

  http.get('/api/auth/me', ({ request }) => {
    const auth = request.headers.get('Authorization')
    if (auth === `Bearer ${TEST_TOKEN}`) {
      return HttpResponse.json({ ...TEST_USER, is_active: true })
    }
    return HttpResponse.json({ detail: 'Not authenticated' }, { status: 401 })
  }),
]
