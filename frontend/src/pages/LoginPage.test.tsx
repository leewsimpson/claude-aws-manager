import { describe, expect, it, vi } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LoginPage } from './LoginPage'
import { renderWithProviders } from '../test/utils'
import { TEST_TOKEN, ADMIN_TOKEN } from '../mocks/handlers'

// Drive the test-mode branch deterministically, independent of VITE_TEST_MODE.
vi.mock('../config', () => ({
  TEST_MODE: true,
  TEST_PERSONAS: [
    { username: 'admin', password: 'admin', displayName: 'Admin User', roles: ['admin'] },
    { username: 'dev1', password: 'dev1', displayName: 'Developer One', roles: ['developer'] },
  ],
}))

function renderLogin() {
  return renderWithProviders(
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<div>Home content</div>} />
    </Routes>,
    { initialEntries: ['/login'] },
  )
}

describe('LoginPage', () => {
  it('logs in with valid credentials, stores the token and navigates home', async () => {
    const user = userEvent.setup()
    renderLogin()

    await user.type(screen.getByLabelText('Username'), 'dev1')
    await user.type(screen.getByLabelText('Password'), 'dev1')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => expect(screen.getByText('Home content')).toBeInTheDocument())
    expect(localStorage.getItem('cam.token')).toBe(TEST_TOKEN)
  })

  it('shows an inline error on invalid credentials', async () => {
    const user = userEvent.setup()
    renderLogin()

    await user.type(screen.getByLabelText('Username'), 'dev1')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /incorrect username or password/i,
    )
    expect(localStorage.getItem('cam.token')).toBeNull()
  })

  it('disables the submit button while the request is pending', async () => {
    const user = userEvent.setup()
    renderLogin()

    await user.type(screen.getByLabelText('Username'), 'dev1')
    await user.type(screen.getByLabelText('Password'), 'dev1')
    const button = screen.getByRole('button', { name: /sign in/i })
    await user.click(button)

    // Immediately after click the request is in flight; button is disabled.
    expect(button).toBeDisabled()
    await waitFor(() => expect(screen.getByText('Home content')).toBeInTheDocument())
  })

  it('lists personas and logs in on click when in test mode', async () => {
    const user = userEvent.setup()
    renderLogin()

    await user.click(screen.getByRole('button', { name: /Admin User/i }))

    await waitFor(() => expect(screen.getByText('Home content')).toBeInTheDocument())
    expect(localStorage.getItem('cam.token')).toBe(ADMIN_TOKEN)
  })
})
