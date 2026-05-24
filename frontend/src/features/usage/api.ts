// Typed request functions + TanStack Query hooks for usage/cost tracking.
// Every call goes through the shared api<T> wrapper and carries the bearer
// token from useAuth(). Query keys follow the same [domain, id?] pattern as
// the other feature modules.

import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/api'
import { useAuth } from '../../auth/AuthContext'
import type { KeyUsage, CostCentreUsage, UsageSummary } from './types'

const USAGE_KEY = ['usage'] as const

export function useKeyUsage(keyId: string | null) {
  const { token } = useAuth()
  return useQuery({
    queryKey: [...USAGE_KEY, 'key', keyId] as const,
    queryFn: () => api<KeyUsage>(`/keys/${keyId!}/usage`, { token }),
    enabled: Boolean(token) && Boolean(keyId),
  })
}

export function useCostCentreUsage(ccId: string | null) {
  const { token } = useAuth()
  return useQuery({
    queryKey: [...USAGE_KEY, 'cost-centre', ccId] as const,
    queryFn: () => api<CostCentreUsage>(`/cost-centres/${ccId!}/usage`, { token }),
    enabled: Boolean(token) && Boolean(ccId),
  })
}

export function useUsageSummary() {
  const { token } = useAuth()
  return useQuery({
    queryKey: [...USAGE_KEY, 'summary'] as const,
    queryFn: () => api<UsageSummary>('/usage/summary', { token }),
    enabled: Boolean(token),
  })
}
