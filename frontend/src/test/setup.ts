import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from '../mocks/server'
import { resetCostCentreStore, resetKeyRequestStore, resetKeyStore } from '../mocks/handlers'

// Start the MSW mock API for the whole test run.
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  resetCostCentreStore()
  resetKeyRequestStore()
  resetKeyStore()
  localStorage.clear()
})
afterAll(() => server.close())
