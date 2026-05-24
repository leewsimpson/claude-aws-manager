// Thin fetch wrapper. Prefixes /api (so the Vite proxy handles dev + Docker),
// attaches the bearer token when supplied, parses JSON, and throws ApiError on
// any non-2xx response so callers can branch on status (notably 401).

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `Request failed with status ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

interface ApiOptions {
  method?: string
  body?: unknown
  token?: string | null
}

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const { method = 'GET', body, token } = options

  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers['Authorization'] = `Bearer ${token}`

  const response = await fetch(`/api${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  // Some endpoints (e.g. 204) have no body; guard JSON parsing.
  const text = await response.text()
  const data = text ? safeParse(text) : null

  if (!response.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data
        ? (data as { detail: unknown }).detail
        : data
    const message = typeof detail === 'string' ? detail : undefined
    throw new ApiError(response.status, detail, message)
  }

  return data as T
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}
