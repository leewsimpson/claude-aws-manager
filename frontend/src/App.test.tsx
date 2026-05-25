import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import App from './App'
import { renderWithProviders } from './test/utils'
import { ADMIN_TOKEN, CCO_TOKEN, TEST_TOKEN } from './mocks/handlers'

// Renders the real <App/> routes with a restored session, exercising the
// post-login redirect (HomeRedirect) and the role-aware nav (AppLayout) end to
// end — the tests below all start at "/" the way a fresh login arrives.
function renderAppAt(token: string) {
  localStorage.setItem('cam.token', token)
  return renderWithProviders(<App />, { initialEntries: ['/'] })
}

function navLink(name: string) {
  return screen.queryByRole('link', { name })
}

describe('App role-aware landing', () => {
  it('lands a developer on Keys with a developer-scoped nav', async () => {
    renderAppAt(TEST_TOKEN)
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Keys' })).toBeInTheDocument(),
    )
    expect(navLink('Keys')).toBeInTheDocument()
    expect(navLink('Key requests')).toBeInTheDocument()
    expect(navLink('Usage')).not.toBeInTheDocument()
    expect(navLink('Cost centres')).not.toBeInTheDocument()
  })

  it('lands a CCO on Key requests with a reviewer-scoped nav', async () => {
    renderAppAt(CCO_TOKEN)
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Key requests' })).toBeInTheDocument(),
    )
    expect(navLink('Key requests')).toBeInTheDocument()
    expect(navLink('Keys')).toBeInTheDocument()
    // CCOs manage their own cost centres' request defaults, so they get the link.
    expect(navLink('Cost centres')).toBeInTheDocument()
    expect(navLink('Usage')).not.toBeInTheDocument()
  })

  it('lets a CCO reach the Cost centres page they manage', async () => {
    localStorage.setItem('cam.token', CCO_TOKEN)
    renderWithProviders(<App />, { initialEntries: ['/cost-centres'] })
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: 'Cost centres' }),
      ).toBeInTheDocument(),
    )
  })

  it('lands an admin on the Usage overview with the full nav', async () => {
    renderAppAt(ADMIN_TOKEN)
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: 'Organisation usage' }),
      ).toBeInTheDocument(),
    )
    for (const label of ['Usage', 'Cost centres', 'Key requests', 'Keys']) {
      expect(navLink(label)).toBeInTheDocument()
    }
  })

  it('bounces a developer off the admin-only Usage route to their role home', async () => {
    localStorage.setItem('cam.token', TEST_TOKEN)
    renderWithProviders(<App />, { initialEntries: ['/usage'] })
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Keys' })).toBeInTheDocument(),
    )
    expect(
      screen.queryByRole('heading', { name: 'Organisation usage' }),
    ).not.toBeInTheDocument()
  })

  it('bounces a developer off the Cost centres route to their role home', async () => {
    localStorage.setItem('cam.token', TEST_TOKEN)
    renderWithProviders(<App />, { initialEntries: ['/cost-centres'] })
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Keys' })).toBeInTheDocument(),
    )
    expect(
      screen.queryByRole('heading', { name: 'Cost centres' }),
    ).not.toBeInTheDocument()
  })
})
