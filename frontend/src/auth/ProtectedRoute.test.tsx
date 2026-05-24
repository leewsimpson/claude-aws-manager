import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { screen, waitFor } from '@testing-library/react'
import { ProtectedRoute } from './ProtectedRoute'
import { renderWithProviders } from '../test/utils'
import { TEST_TOKEN } from '../mocks/handlers'

function renderRoutes() {
  return renderWithProviders(
    <Routes>
      <Route path="/login" element={<div>Login page</div>} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <div>Protected content</div>
          </ProtectedRoute>
        }
      />
    </Routes>,
    { initialEntries: ['/'] },
  )
}

describe('ProtectedRoute', () => {
  it('redirects to /login when there is no token', async () => {
    renderRoutes()
    await waitFor(() => expect(screen.getByText('Login page')).toBeInTheDocument())
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument()
  })

  it('renders protected content when a valid token restores the session', async () => {
    localStorage.setItem('cam.token', TEST_TOKEN)
    renderRoutes()
    await waitFor(() =>
      expect(screen.getByText('Protected content')).toBeInTheDocument(),
    )
  })
})
