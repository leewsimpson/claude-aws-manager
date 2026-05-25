import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from '../mocks/server'
import { resetCostCentreStore, resetKeyRequestStore, resetKeyStore } from '../mocks/handlers'

// Node 22+ ships a native globalThis.localStorage that is undefined unless
// --localstorage-file is provided. This shadows jsdom's window.localStorage.
// Patch globalThis so code using the bare `localStorage` identifier works.
if (typeof globalThis.localStorage === 'undefined') {
  // In jsdom environment, window.localStorage is provided by jsdom.
  // Fall back to a simple in-memory shim if window is also missing.
  if (typeof window !== 'undefined' && window.localStorage) {
    Object.defineProperty(globalThis, 'localStorage', {
      value: window.localStorage,
      writable: true,
      configurable: true,
    })
  } else {
    const store = new Map<string, string>()
    Object.defineProperty(globalThis, 'localStorage', {
      value: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => store.set(key, String(value)),
        removeItem: (key: string) => store.delete(key),
        clear: () => store.clear(),
        get length() { return store.size },
        key: (index: number) => [...store.keys()][index] ?? null,
      },
      writable: true,
      configurable: true,
    })
  }
}

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
