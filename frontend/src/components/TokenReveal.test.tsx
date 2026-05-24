import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TokenReveal } from './TokenReveal'
import type { ProvisionedKey } from '../features/keyRequests/types'

const MOCK_KEY: ProvisionedKey = {
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

describe('TokenReveal — clipboard', () => {
  it('copy bearer token button writes to clipboard and shows Copied! feedback', async () => {
    // userEvent.setup() installs its own clipboard mock for the test environment.
    // We spy on that mock after setup so our spy reference matches what the
    // component actually calls.
    const user = userEvent.setup()
    // After setup(), navigator.clipboard is the userEvent clipboard; spy on it.
    const writeTextSpy = vi.spyOn(navigator.clipboard, 'writeText')

    const onDismiss = vi.fn()
    render(<TokenReveal provisionedKey={MOCK_KEY} onDismiss={onDismiss} />)

    expect(screen.getByText(/store this token now/i)).toBeInTheDocument()

    const copyBtn = screen.getByRole('button', { name: /copy bearer token/i })
    await user.click(copyBtn)

    // Verify the button shows Copied! feedback (proves writeToClipboard returned true)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /copy bearer token/i })).toHaveTextContent('Copied!')
    })

    // Verify writeText was called with the exact bearer token
    expect(writeTextSpy).toHaveBeenCalledWith('mock-bearer-token-abc123')

    writeTextSpy.mockRestore()
  })
})
