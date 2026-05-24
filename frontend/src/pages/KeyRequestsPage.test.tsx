import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { KeyRequestsPage } from './KeyRequestsPage'
import { renderWithProviders } from '../test/utils'
import {
  ADMIN_TOKEN,
  CCO_TOKEN,
  TEST_TOKEN,
  seedPendingKeyRequest,
} from '../mocks/handlers'

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

    // Wait for page to render
    await screen.findByRole('heading', { name: /request a key/i })
    // Reviewer section heading should not be present
    expect(screen.queryByRole('heading', { name: /pending requests/i })).not.toBeInTheDocument()
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

  it('shows TokenReveal with bearer token on auto-approval', async () => {
    // The seed CC cc-1 has ccowner1 as an owner, so a CCO submitting for cc-1
    // is auto-approved in the mock handler.
    const user = userEvent.setup()
    renderPage(CCO_TOKEN)

    await screen.findByRole('heading', { name: /request a key/i })
    await waitForCostCentreOptions()

    await user.selectOptions(
      screen.getByLabelText(/cost centre/i),
      ['cc-1'],
    )
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    // TokenReveal should appear with the bearer token warning
    expect(
      await screen.findByText(/store this token now/i),
    ).toBeInTheDocument()

    // Copy button should be present
    expect(
      screen.getByRole('button', { name: /copy bearer token/i }),
    ).toBeInTheDocument()
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

  it('admin can approve a request and sees TokenReveal', async () => {
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

    // TokenReveal should appear
    expect(await screen.findByText(/store this token now/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /copy bearer token/i })).toBeInTheDocument()
  })

  it('admin can reject a request with a reason', async () => {
    const user = userEvent.setup()
    seedPendingKeyRequest()
    renderPage(ADMIN_TOKEN)

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
