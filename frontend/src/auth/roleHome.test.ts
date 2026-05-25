import { describe, expect, it } from 'vitest'
import { roleHome } from './roleHome'

describe('roleHome', () => {
  it('sends admins to the usage overview', () => {
    expect(roleHome(['admin'])).toBe('/usage')
  })

  it('sends CCOs to the approvals queue', () => {
    expect(roleHome(['cco'])).toBe('/key-requests')
  })

  it('sends developers to their keys', () => {
    expect(roleHome(['developer'])).toBe('/keys')
  })

  it('honours admin → cco → developer precedence for multi-role users', () => {
    expect(roleHome(['developer', 'cco', 'admin'])).toBe('/usage')
    expect(roleHome(['developer', 'cco'])).toBe('/key-requests')
  })

  it('falls back to keys when no known role is held', () => {
    expect(roleHome([])).toBe('/keys')
  })
})
