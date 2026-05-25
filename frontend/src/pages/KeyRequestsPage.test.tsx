import { describe, expect, it, vi } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { KeyRequestsPage } from './KeyRequestsPage'
import { TokenReveal } from '../components/TokenReveal'
import { renderWithProviders } from '../test/utils'
import {
  ADMIN_TOKEN,
  CCO_TOKEN,
  TEST_TOKEN,
  seedPendingKeyRequest,
} from '../mocks/handlers'
import { server } from '../mocks/server'
import type { ProvisionedKey } from '../features/keyRequests/types'

function renderPage(token: string) {
  localStorage.setItem('cam.token', token)
  return renderWithProviders(
    <Routes>
      <Route path="/key-requests" element={<KeyRequestsPage />} />
    </Routes>,
    { initialEntries: ['/key-requests'] },
  )
}

/** Wait until the cost-centre select has loaded its options from the API. */
async function waitForCostCentreOptions() {
  // The select populates async; wait for at least one real option to appear.
  await screen.findByRole('option', { name: /ENG/i })
}

describe('KeyRequestsPage — developer', () => {
  it('renders the request form with a cost centre selector', async () => {
    renderPage(TEST_TOKEN)

    expect(await screen.findByRole('heading', { name: /request a key/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/cost centre/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/justification/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /submit request/i })).toBeInTheDocument()
  })

  it('does NOT show the pending requests reviewer section for a developer', async () => {
    renderPage(TEST_TOKEN)

    // Wait for page to fully render
    await screen.findByRole('heading', { name: /request a key/i })
    // Reviewer section heading should not be present
    expect(screen.queryByRole('heading', { name: /pending requests/i })).not.toBeInTheDocument()
    // Approve/Reject action buttons should not be present
    expect(screen.queryByRole('button', { name: /^approve$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^reject$/i })).not.toBeInTheDocument()
  })

  it('developer can submit a request and it appears in My requests', async () => {
    const user = userEvent.setup()
    renderPage(TEST_TOKEN)

    await screen.findByRole('heading', { name: /request a key/i })
    await waitForCostCentreOptions()

    // Select a cost centre
    await user.selectOptions(
      screen.getByLabelText(/cost centre/i),
      ['cc-1'],
    )
    await user.type(screen.getByLabelText(/justification/i), 'Need for project X')
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    // Should appear in My requests with pending status
    expect(await screen.findByText('pending')).toBeInTheDocument()
  })

  it('directs a CCO to the Keys page (no token) on auto-approval', async () => {
    // The seed CC cc-1 has ccowner1 as an owner, so a CCO submitting for cc-1
    // is auto-approved in the mock handler. The token is NOT revealed here —
    // the CCO retrieves it from the Keys page like any developer.
    const user = userEvent.setup()
    renderPage(CCO_TOKEN)

    await screen.findByRole('heading', { name: /request a key/i })
    await waitForCostCentreOptions()

    await user.selectOptions(
      screen.getByLabelText(/cost centre/i),
      ['cc-1'],
    )
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    // A confirmation directs the user to the Keys page — and no token is shown.
    expect(
      await screen.findByText(/keys page to retrieve your token/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/store this token now/i)).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /copy bearer token/i }),
    ).not.toBeInTheDocument()
  })

  it('shows conflict error when submitting a duplicate request', async () => {
    const user = userEvent.setup()
    renderPage(TEST_TOKEN)

    await screen.findByRole('heading', { name: /request a key/i })
    await waitForCostCentreOptions()

    // First submission
    await user.selectOptions(screen.getByLabelText(/cost centre/i), ['cc-1'])
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    await screen.findByText('pending')

    // Second submission — should 409
    await user.selectOptions(screen.getByLabelText(/cost centre/i), ['cc-1'])
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /active or pending request/i,
    )
  })
})

describe('KeyRequestsPage — reviewer (admin)', () => {
  it('shows pending requests section for admin', async () => {
    renderPage(ADMIN_TOKEN)

    await screen.findByRole('heading', { name: /key requests/i })
    expect(screen.getByRole('heading', { name: /pending requests/i })).toBeInTheDocument()
  })

  it('admin sees pending requests submitted by developers', async () => {
    // Pre-seed a pending request directly into the store.
    seedPendingKeyRequest()
    renderPage(ADMIN_TOKEN)

    // Developer's request should appear in pending list
    expect(await screen.findByText('Developer One (dev1)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^approve$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^reject$/i })).toBeInTheDocument()
  })

  it('admin approval shows a confirmation and never reveals a token', async () => {
    const user = userEvent.setup()
    seedPendingKeyRequest()
    renderPage(ADMIN_TOKEN)

    // Wait for pending request row
    await screen.findByText('Developer One (dev1)')

    // Open approve panel (row button → "Close" after click)
    await user.click(screen.getByRole('button', { name: /^approve$/i }))
    expect(await screen.findByRole('heading', { name: /approve request/i })).toBeInTheDocument()

    // Now the row button says "Close"; only the form submit says "Approve"
    await user.click(screen.getByRole('button', { name: /^approve$/i }))

    // A confirmation appears stating the developer will retrieve the key…
    expect(
      await screen.findByText(/will retrieve their key from the Keys page/i),
    ).toBeInTheDocument()
    // …and the approver is NEVER shown the token.
    expect(screen.queryByText(/store this token now/i)).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /copy bearer token/i }),
    ).not.toBeInTheDocument()
  })

  it('admin can reject a request and the POST body carries rejection_reason', async () => {
    const user = userEvent.setup()
    seedPendingKeyRequest()
    renderPage(ADMIN_TOKEN)

    // Capture the reject request body via MSW lifecycle events.
    // server.events picks on/removeListener/removeAllListeners from the emitter.
    let capturedBody: Record<string, unknown> | null = null
    const listener = async ({ request }: { request: Request }) => {
      if (request.method === 'POST' && request.url.includes('/reject')) {
        // Clone so MSW can still read the body for the handler
        capturedBody = (await request.clone().json()) as Record<string, unknown>
      }
    }
    server.events.on('request:start', listener)

    await screen.findByText('Developer One (dev1)')

    // Open reject panel (row button → "Close" after click)
    await user.click(screen.getByRole('button', { name: /^reject$/i }))
    expect(await screen.findByRole('heading', { name: /reject request/i })).toBeInTheDocument()

    // Enter reason and submit — row button now says "Close", form submit says "Reject"
    await user.type(
      screen.getByLabelText(/rejection reason/i),
      'Not approved at this time.',
    )
    await user.click(screen.getByRole('button', { name: /^reject$/i }))

    // Panel should close
    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: /reject request/i })).not.toBeInTheDocument(),
    )

    // The POST body must have carried the rejection_reason
    await waitFor(() => {
      expect(capturedBody).not.toBeNull()
      expect(capturedBody?.rejection_reason).toBe('Not approved at this time.')
    })

    server.events.removeListener('request:start', listener)
  })
})

describe('KeyRequestsPage — reviewer (cco)', () => {
  it('shows pending requests section for a CCO user', async () => {
    renderPage(CCO_TOKEN)

    await screen.findByRole('heading', { name: /key requests/i })
    expect(screen.getByRole('heading', { name: /pending requests/i })).toBeInTheDocument()
  })

  it('CCO can see and act on pending requests', async () => {
    // Pre-seed a pending request directly into the store.
    seedPendingKeyRequest()
    renderPage(CCO_TOKEN)

    await screen.findByText('Developer One (dev1)')
    expect(screen.getByRole('button', { name: /^approve$/i })).toBeInTheDocument()
  })
})

describe('TokenReveal — copy button', () => {
  it('copy bearer token button writes to clipboard and shows Copied! feedback', async () => {
    // userEvent.setup() installs its own clipboard implementation. Spy on it after
    // setup so our spy reference matches what the component actually invokes.
    const user = userEvent.setup()
    const writeTextSpy = vi.spyOn(navigator.clipboard, 'writeText')

    const mockKey: ProvisionedKey = {
      id: 'key-test',
      cost_centre_id: 'cc-1',
      cost_centre_code: 'ENG',
      iam_username: 'claude-dev1-eng',
      status: 'active',
      allowed_models: ['anthropic.claude-sonnet-4-6'],
      rolling_limit: null,
      rolling_period_days: null,
      lifetime_budget: null,
      expires_at: null,
      bearer_token: 'mock-bearer-token-abc123',
      inference_profiles: [],
    }

    const onDismiss = vi.fn()
    render(<TokenReveal provisionedKey={mockKey} onDismiss={onDismiss} />)

    // TokenReveal should be visible
    expect(screen.getByText(/store this token now/i)).toBeInTheDocument()

    // Click the copy bearer token button
    const copyBtn = screen.getByRole('button', { name: /copy bearer token/i })
    await user.click(copyBtn)

    // Button shows "Copied!" feedback (proves the copy path succeeded)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /copy bearer token/i })).toHaveTextContent('Copied!')
    })
    // Verify writeText was called with the exact bearer token
    expect(writeTextSpy).toHaveBeenCalledWith('mock-bearer-token-abc123')

    writeTextSpy.mockRestore()
  })
})
