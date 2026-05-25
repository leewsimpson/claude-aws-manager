// Typed request functions + TanStack Query hooks for cost-centre management.
// Every call goes through the shared api<T> wrapper and carries the bearer
// token from useAuth(). Mutations invalidate ['cost-centres'] so the list
// (and any open detail) refetches with fresh server state.

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { api } from '../../lib/api'
import { useAuth } from '../../auth/AuthContext'
import type {
  CostCentre,
  CreateCostCentreInput,
  RequestDefaults,
  UpdateCostCentreInput,
  UserListItem,
} from './types'

const COST_CENTRES_KEY = ['cost-centres'] as const

export function useCostCentres() {
  const { token } = useAuth()
  return useQuery({
    queryKey: COST_CENTRES_KEY,
    queryFn: () => api<CostCentre[]>('/cost-centres', { token }),
    enabled: Boolean(token),
  })
}

export function useUsers(enabled = true) {
  const { token } = useAuth()
  return useQuery({
    queryKey: ['users'],
    queryFn: () => api<UserListItem[]>('/users', { token }),
    enabled: enabled && Boolean(token),
  })
}

export function useCreateCostCentre() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateCostCentreInput) =>
      api<CostCentre>('/cost-centres', { method: 'POST', body: input, token }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: COST_CENTRES_KEY })
    },
  })
}

export function useUpdateCostCentre() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: UpdateCostCentreInput }) =>
      api<CostCentre>(`/cost-centres/${id}`, {
        method: 'PATCH',
        body: input,
        token,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: COST_CENTRES_KEY })
    },
  })
}

export function useArchiveCostCentre() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      api<CostCentre>(`/cost-centres/${id}/archive`, {
        method: 'POST',
        token,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: COST_CENTRES_KEY })
    },
  })
}

export function useUnarchiveCostCentre() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      api<CostCentre>(`/cost-centres/${id}/unarchive`, {
        method: 'POST',
        token,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: COST_CENTRES_KEY })
    },
  })
}

export function useAssignOwner() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, userId }: { id: string; userId: string }) =>
      api<CostCentre>(`/cost-centres/${id}/owners`, {
        method: 'POST',
        body: { user_id: userId },
        token,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: COST_CENTRES_KEY })
    },
  })
}

export function useRemoveOwner() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, userId }: { id: string; userId: string }) =>
      api<CostCentre>(`/cost-centres/${id}/owners/${userId}`, {
        method: 'DELETE',
        token,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: COST_CENTRES_KEY })
    },
  })
}

export function useCcDefaults(ccId: string | null) {
  const { token } = useAuth()
  return useQuery({
    queryKey: [...COST_CENTRES_KEY, ccId, 'defaults'] as const,
    queryFn: () => api<RequestDefaults | null>(`/cost-centres/${ccId}/defaults`, { token }),
    enabled: Boolean(token) && Boolean(ccId),
  })
}

export function useUpdateCcDefaults() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: RequestDefaults }) =>
      api<CostCentre>(`/cost-centres/${id}/defaults`, {
        method: 'PUT',
        body: input,
        token,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: COST_CENTRES_KEY })
    },
  })
}
