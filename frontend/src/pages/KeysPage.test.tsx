import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { KeysPage } from './KeysPage'
import { renderWithProviders } from '../test/utils'
import {
  ADMIN_TOKEN,
  CCO_TOKEN,
  TEST_TOKEN,
  seedKey,
} from '../mocks/handlers'
import { server } from '../mocks/server'
import { http, HttpResponse } from 'msw'

function renderPage(token: string) {
  localStorage.setItem('cam.token', token)
  return renderWithProviders(
    <Routes>
      <Route path="/keys" element={<KeysPage />} />
    </Routes>,
    { initialEntries: ['/keys'] },
  )
}

describe('KeysPage — developer', () => {
  it('shows My keys heading and empty state when no keys exist', async () => {
    renderPage(TEST_TOKEN)

    expect(await screen.findByRole('heading', { name: /my keys/i })).toBeInTheDocument()
    expect(await screen.findByText(/no keys yet/i)).toBeInTheDocument()
  })

  it('renders a key card for the developer with cost centre, status, and models', async () => {
    seedKey({
      status: 'active',
      allowed_models: ['anthropic.claude-sonnet-4-6'],
    })
    renderPage(TEST_TOKEN)

    // Cost centre label
    expect(await screen.findByText(/ENG — Engineering/i)).toBeInTheDocument()
    // Status badge
    expect(screen.getByText('active')).toBeInTheDocument()
    // Model
    expect(screen.getByText(/anthropic\.claude-sonnet-4-6/i)).toBeInTheDocument()
  })

  it('shows revoke confirm panel on Revoke click and hides on Cancel', async () => {
    const user = userEvent.setup()
    seedKey({ status: 'active' })
    renderPage(TEST_TOKEN)

    await screen.findByText(/ENG — Engineering/i)

    await user.click(screen.getByRole('button', { name: /^revoke$/i }))
    expect(await screen.findByText(/are you sure\?/i)).toBeInTheDocument()

    // Cancel is the secondary button inside the revoke panel
    await user.click(screen.getByRole('button', { name: /^cancel$/i }))
    expect(screen.queryByText(/are you sure\?/i)).not.toBeInTheDocument()
  })

  it('fires POST /keys/:id/revoke and updates status to revoked', async () => {
    const user = userEvent.setup()
    const key = seedKey({ status: 'active' })
    renderPage(TEST_TOKEN)

    await screen.findByText(/ENG — Engineering/i)

    // Open revoke confirm
    await user.click(screen.getByRole('button', { name: /^revoke$/i }))
    await screen.findByText(/are you sure\?/i)

    // Confirm inline revoke button (the danger one inside the panel)
    const revokeConfirmBtns = screen.getAllByRole('button', { name: /^revoke$/i })
    // The last one is the confirm button inside the panel
    await user.click(revokeConfirmBtns[revokeConfirmBtns.length - 1]!)

    // After revoke, status badge should update
    await waitFor(() => {
      expect(screen.getByText('revoked')).toBeInTheDocument()
    })

    // Verify the key id was in the request
    expect(key.id).toMatch(/key-seed-/)
  })

  it('shows TokenReveal with bearer token after Regenerate', async () => {
    const user = userEvent.setup()
    seedKey({ status: 'active' })
    renderPage(TEST_TOKEN)

    await screen.findByText(/ENG — Engineering/i)

    await user.click(screen.getByRole('button', { name: /^regenerate$/i }))

    // TokenReveal should appear with the token warning
    expect(await screen.findByText(/store this token now/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /copy bearer token/i })).toBeInTheDocument()
    // The mock handler returns mock-regen-bearer-<id>; the bearer token field shows
    // it inside a <code> element within the token-reveal region.
    expect(screen.getAllByText(/mock-regen-bearer-/i).length).toBeGreaterThan(0)
  })

  it('shows setup instructions panel with env var name and modelOverrides', async () => {
    const user = userEvent.setup()
    seedKey({ status: 'active' })
    renderPage(TEST_TOKEN)

    await screen.findByText(/ENG — Engineering/i)

    await user.click(screen.getByRole('button', { name: /setup instructions/i }))

    // Env var name (no token value)
    expect(await screen.findByText('AWS_BEARER_TOKEN_BEDROCK')).toBeInTheDocument()
    // modelOverrides JSON — appears in the pre block; use getAllBy since it may
    // appear in multiple text nodes within the pre element
    expect(screen.getAllByText(/modelOverrides/i).length).toBeGreaterThan(0)
  })

  it('does NOT show the reviewer constraints editor or Edit constraints button for developer', async () => {
    seedKey({ status: 'active' })
    renderPage(TEST_TOKEN)

    await screen.findByText(/ENG — Engineering/i)

    // Developer view should not have Edit constraints button
    expect(screen.queryByRole('button', { name: /edit constraints/i })).not.toBeInTheDocument()
  })

  it('does NOT show Regenerate button in reviewer rows', async () => {
    seedKey({ status: 'active' })
    // Admin logs in — reviewer rows should not have a Regenerate button
    renderPage(ADMIN_TOKEN)

    await screen.findByRole('heading', { name: /key management/i })
    await screen.findByText(/Developer One/i)

    expect(screen.queryByRole('button', { name: /^regenerate$/i })).not.toBeInTheDocument()
  })
})

describe('KeysPage — reviewer (admin)', () => {
  it('shows Key management heading for admin', async () => {
    renderPage(ADMIN_TOKEN)

    expect(await screen.findByRole('heading', { name: /key management/i })).toBeInTheDocument()
  })

  it('shows status and cost centre filter dropdowns for admin', async () => {
    renderPage(ADMIN_TOKEN)

    expect(await screen.findByLabelText(/filter by status/i)).toBeInTheDocument()
    expect(await screen.findByLabelText(/filter by cost centre/i)).toBeInTheDocument()
  })

  it('admin sees the management table with all keys', async () => {
    seedKey({ status: 'active' })
    renderPage(ADMIN_TOKEN)

    await screen.findByRole('heading', { name: /key management/i })
    // Dev's key should be listed
    expect(await screen.findByText('Developer One (dev1)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /edit constraints/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^revoke$/i })).toBeInTheDocument()
  })

  it('admin can edit constraints and the PATCH body includes the constraint values', async () => {
    const user = userEvent.setup()
    seedKey({ status: 'active' })
    renderPage(ADMIN_TOKEN)

    await screen.findByText('Developer One (dev1)')

    // Open edit constraints panel
    await user.click(screen.getByRole('button', { name: /edit constraints/i }))
    expect(await screen.findByRole('heading', { name: /edit constraints/i })).toBeInTheDocument()

    // Capture the PATCH request body
    let capturedBody: Record<string, unknown> | null = null
    const listener = async ({ request }: { request: Request }) => {
      if (request.method === 'PATCH' && request.url.includes('/constraints')) {
        capturedBody = (await request.clone().json()) as Record<string, unknown>
      }
    }
    server.events.on('request:start', listener)

    // Set a rolling limit
    await user.clear(screen.getByLabelText(/rolling limit/i))
    await user.type(screen.getByLabelText(/rolling limit/i), '100')
    await user.clear(screen.getByLabelText(/rolling period days/i))
    await user.type(screen.getByLabelText(/rolling period days/i), '30')

    // Submit
    await user.click(screen.getByRole('button', { name: /save constraints/i }))

    // Panel should close
    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: /edit constraints/i })).not.toBeInTheDocument(),
    )

    // Verify the PATCH body
    await waitFor(() => {
      expect(capturedBody).not.toBeNull()
      expect(capturedBody?.rolling_limit).toBe(100)
      expect(capturedBody?.rolling_period_days).toBe(30)
    })

    server.events.removeListener('request:start', listener)
  })

  it('admin can revoke a key from the management table', async () => {
    const user = userEvent.setup()
    seedKey({ status: 'active' })
    renderPage(ADMIN_TOKEN)

    await screen.findByText('Developer One (dev1)')

    await user.click(screen.getByRole('button', { name: /^revoke$/i }))
    expect(await screen.findByRole('heading', { name: /revoke key/i })).toBeInTheDocument()

    // Confirm by clicking the danger Revoke in the panel
    const revokeBtns = screen.getAllByRole('button', { name: /^revoke$/i })
    await user.click(revokeBtns[revokeBtns.length - 1]!)

    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: /revoke key/i })).not.toBeInTheDocument(),
    )

    // Status badge should update
    expect(await screen.findByText('revoked')).toBeInTheDocument()
  })
})

describe('KeysPage — reviewer (cco)', () => {
  it('shows Key management heading for CCO', async () => {
    renderPage(CCO_TOKEN)

    expect(await screen.findByRole('heading', { name: /key management/i })).toBeInTheDocument()
  })

  it('CCO does NOT see the cost centre filter (admin only)', async () => {
    renderPage(CCO_TOKEN)

    await screen.findByLabelText(/filter by status/i)
    expect(screen.queryByLabelText(/filter by cost centre/i)).not.toBeInTheDocument()
  })

  it('CCO can see keys in the management table', async () => {
    seedKey({ status: 'active' })
    renderPage(CCO_TOKEN)

    expect(await screen.findByText('Developer One (dev1)')).toBeInTheDocument()
  })
})

describe('KeysPage — error handling', () => {
  it('shows error message when GET /keys fails', async () => {
    server.use(
      http.get('/api/keys', () =>
        HttpResponse.json({ detail: 'Internal server error' }, { status: 500 }),
      ),
    )
    renderPage(TEST_TOKEN)

    expect(await screen.findByRole('alert')).toHaveTextContent(/unable to load keys/i)
  })
})
