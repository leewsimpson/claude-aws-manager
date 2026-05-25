// Typed request functions + TanStack Query hooks for key management.
// Every call goes through the shared api<T> wrapper and carries the bearer
// token from useAuth(). Mutations invalidate ['keys'] so the list refetches.

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { api } from '../../lib/api'
import { useAuth } from '../../auth/AuthContext'
import type { Key, KeyFilters, UpdateKeyConstraintsInput } from './types'
import type { ProvisionedKey } from '../keyRequests/types'

const KEYS_KEY = ['keys'] as const

export function useKeys(filters?: KeyFilters) {
  const { token } = useAuth()
  return useQuery({
    queryKey: [...KEYS_KEY, filters ?? {}] as const,
    queryFn: () => {
      const params = new URLSearchParams()
      if (filters?.status) params.set('status', filters.status)
      if (filters?.cost_centre_id) params.set('cost_centre_id', filters.cost_centre_id)
      if (filters?.developer_id) params.set('developer_id', filters.developer_id)
      const qs = params.toString()
      return api<Key[]>(qs ? `/keys?${qs}` : '/keys', { token })
    },
    enabled: Boolean(token),
  })
}

export function useRevokeKey() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      api<Key>(`/keys/${id}/revoke`, { method: 'POST', token }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KEYS_KEY })
    },
  })
}

export function useRegenerateKey() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      api<ProvisionedKey>(`/keys/${id}/regenerate`, { method: 'POST', token }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KEYS_KEY })
    },
  })
}

// First-time claim of a 'ready' key: issues the credential and reveals the
// bearer token once (the approver never sees it).
export function useRetrieveToken() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      api<ProvisionedKey>(`/keys/${id}/retrieve`, { method: 'POST', token }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KEYS_KEY })
    },
  })
}

export function useUpdateKeyConstraints() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: UpdateKeyConstraintsInput }) =>
      api<Key>(`/keys/${id}/constraints`, { method: 'PATCH', body: input, token }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KEYS_KEY })
    },
  })
}
