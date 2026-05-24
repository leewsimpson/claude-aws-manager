import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CostCentresPage } from './CostCentresPage'
import { renderWithProviders } from '../test/utils'
import { ADMIN_TOKEN, TEST_TOKEN } from '../mocks/handlers'

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/cost-centres" element={<CostCentresPage />} />
    </Routes>,
    { initialEntries: ['/cost-centres'] },
  )
}

describe('CostCentresPage', () => {
  it('renders a row per cost centre from the API', async () => {
    localStorage.setItem('cam.token', ADMIN_TOKEN)
    renderPage()

    expect(await screen.findByText('Engineering')).toBeInTheDocument()
    expect(screen.getByText('Data Science')).toBeInTheDocument()
    // Budget cap formatted, and "—" for the null one.
    expect(screen.getByText('ccowner1')).toBeInTheDocument()
  })

  it('shows the create control for admins', async () => {
    localStorage.setItem('cam.token', ADMIN_TOKEN)
    renderPage()

    await screen.findByText('Engineering')
    expect(
      screen.getByRole('heading', { name: /new cost centre/i }),
    ).toBeInTheDocument()
  })

  it('does NOT show the create control for developers', async () => {
    localStorage.setItem('cam.token', TEST_TOKEN)
    renderPage()

    await screen.findByText('Engineering')
    expect(
      screen.queryByRole('heading', { name: /new cost centre/i }),
    ).not.toBeInTheDocument()
    // No per-row action buttons for developers.
    expect(screen.queryByRole('button', { name: /^edit$/i })).not.toBeInTheDocument()
  })

  it('adds a row when an admin creates a cost centre', async () => {
    const user = userEvent.setup()
    localStorage.setItem('cam.token', ADMIN_TOKEN)
    renderPage()

    await screen.findByText('Engineering')

    await user.type(screen.getByLabelText('Code'), 'MKT')
    await user.type(screen.getByLabelText('Name'), 'Marketing')
    await user.click(
      screen.getByRole('button', { name: /create cost centre/i }),
    )

    expect(await screen.findByText('Marketing')).toBeInTheDocument()
    expect(screen.getByText('MKT')).toBeInTheDocument()
  })

  it('surfaces a 409 duplicate-code error inline', async () => {
    const user = userEvent.setup()
    localStorage.setItem('cam.token', ADMIN_TOKEN)
    renderPage()

    await screen.findByText('Engineering')

    await user.type(screen.getByLabelText('Code'), 'ENG')
    await user.type(screen.getByLabelText('Name'), 'Engineering dup')
    await user.click(
      screen.getByRole('button', { name: /create cost centre/i }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /code already exists/i,
    )
  })

  it('toggles status when archiving a cost centre', async () => {
    const user = userEvent.setup()
    localStorage.setItem('cam.token', ADMIN_TOKEN)
    renderPage()

    const nameCell = await screen.findByText('Engineering')
    const row = nameCell.closest('tr') as HTMLTableRowElement
    expect(within(row).getByText('active')).toBeInTheDocument()

    await user.click(within(row).getByRole('button', { name: /archive/i }))

    await waitFor(() =>
      expect(within(row).getByText('archived')).toBeInTheDocument(),
    )
    // Now an Unarchive button is shown.
    expect(
      within(row).getByRole('button', { name: /unarchive/i }),
    ).toBeInTheDocument()
  })
})
