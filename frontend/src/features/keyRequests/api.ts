// Typed request functions + TanStack Query hooks for key request management.
// Every call goes through the shared api<T> wrapper and carries the bearer
// token from useAuth(). Mutations invalidate ['key-requests'] so the list
// refetches with fresh server state.

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { api } from '../../lib/api'
import { useAuth } from '../../auth/AuthContext'
import type {
  ApproveKeyRequestInput,
  CreateKeyRequestInput,
  KeyRequest,
  KeyRequestResult,
  RejectKeyRequestInput,
} from './types'

const KEY_REQUESTS_KEY = ['key-requests'] as const

export function useKeyRequests(status?: string) {
  const { token } = useAuth()
  return useQuery({
    queryKey: [...KEY_REQUESTS_KEY, status ?? 'all'] as const,
    queryFn: () => {
      const path = status
        ? `/key-requests?status=${encodeURIComponent(status)}`
        : '/key-requests'
      return api<KeyRequest[]>(path, { token })
    },
    enabled: Boolean(token),
  })
}

export function useCreateKeyRequest() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateKeyRequestInput) =>
      api<KeyRequestResult>('/key-requests', {
        method: 'POST',
        body: input,
        token,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KEY_REQUESTS_KEY })
    },
  })
}

export function useApproveKeyRequest() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: ApproveKeyRequestInput }) =>
      api<KeyRequestResult>(`/key-requests/${id}/approve`, {
        method: 'POST',
        body: input,
        token,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KEY_REQUESTS_KEY })
    },
  })
}

export function useRejectKeyRequest() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: RejectKeyRequestInput }) =>
      api<KeyRequestResult>(`/key-requests/${id}/reject`, {
        method: 'POST',
        body: input,
        token,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KEY_REQUESTS_KEY })
    },
  })
}
