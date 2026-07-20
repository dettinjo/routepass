'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPatch, apiPost } from '@/lib/api'
import type {
  AdminAlert,
  AdminGovernorConfig,
  AdminGovernorState,
  AdminMetricsOverview,
  AdminProviderOverviewRow,
  AdminProviderPolicy,
  AdminRevenue,
  AdminStravaApp,
  AdminUserDetail,
  AdminUsersPage,
} from '@/types/api'

// ── Overview ──────────────────────────────────────────────────────────────────

export function useAdminMetricsOverview() {
  return useQuery<AdminMetricsOverview>({
    queryKey: ['admin', 'metrics', 'overview'],
    queryFn: () => apiGet<AdminMetricsOverview>('/api/v1/admin/metrics/overview'),
    staleTime: 30_000,
  })
}

export function useAdminRevenue() {
  return useQuery<AdminRevenue>({
    queryKey: ['admin', 'metrics', 'revenue'],
    queryFn: () => apiGet<AdminRevenue>('/api/v1/admin/metrics/revenue'),
    staleTime: 30_000,
  })
}

export function useAdminAlerts() {
  return useQuery<AdminAlert[]>({
    queryKey: ['admin', 'alerts'],
    queryFn: () => apiGet<AdminAlert[]>('/api/v1/admin/alerts'),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
}

// ── Governor ──────────────────────────────────────────────────────────────────

export function useAdminGovernorState() {
  return useQuery<AdminGovernorState>({
    queryKey: ['admin', 'governor', 'state'],
    queryFn: () => apiGet<AdminGovernorState>('/api/v1/admin/governor/state'),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
}

export function useAdminGovernorConfig() {
  return useQuery<AdminGovernorConfig>({
    queryKey: ['admin', 'governor', 'config'],
    queryFn: () => apiGet<AdminGovernorConfig>('/api/v1/admin/governor'),
    staleTime: 30_000,
  })
}

export function useUpdateAdminGovernorConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<AdminGovernorConfig>) =>
      apiPatch<AdminGovernorConfig>('/api/v1/admin/governor', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'governor'] })
      qc.invalidateQueries({ queryKey: ['admin', 'metrics'] })
      qc.invalidateQueries({ queryKey: ['admin', 'alerts'] })
    },
  })
}

export function useRecomputeGovernorState() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost<AdminGovernorState>('/api/v1/admin/governor/state/recompute'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'governor', 'state'] })
      qc.invalidateQueries({ queryKey: ['admin', 'alerts'] })
    },
  })
}

// ── Providers ─────────────────────────────────────────────────────────────────

export function useAdminProviders() {
  return useQuery<AdminProviderPolicy[]>({
    queryKey: ['admin', 'providers'],
    queryFn: () => apiGet<AdminProviderPolicy[]>('/api/v1/admin/providers'),
    staleTime: 30_000,
  })
}

export function useUpdateAdminProvider() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ platform, ...body }: Partial<AdminProviderPolicy> & { platform: string }) =>
      apiPatch<AdminProviderPolicy>(`/api/v1/admin/providers/${platform}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'providers'] })
      qc.invalidateQueries({ queryKey: ['admin', 'metrics', 'providers'] })
    },
  })
}

export function useAdminProvidersOverview() {
  return useQuery<AdminProviderOverviewRow[]>({
    queryKey: ['admin', 'metrics', 'providers'],
    queryFn: () => apiGet<AdminProviderOverviewRow[]>('/api/v1/admin/metrics/providers'),
    staleTime: 30_000,
  })
}

// ── Strava app pool ───────────────────────────────────────────────────────────

export function useAdminStravaApps() {
  return useQuery<AdminStravaApp[]>({
    queryKey: ['admin', 'strava-apps'],
    queryFn: () => apiGet<AdminStravaApp[]>('/api/v1/admin/strava-apps'),
    staleTime: 30_000,
  })
}

export function useCreateAdminStravaApp() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      client_id: string
      client_secret: string
      display_name: string
      athlete_cap?: number
      monthly_cost_cents?: number
    }) => apiPost<AdminStravaApp>('/api/v1/admin/strava-apps', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'strava-apps'] })
      qc.invalidateQueries({ queryKey: ['admin', 'metrics'] })
    },
  })
}

export function useUpdateAdminStravaApp() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: Partial<AdminStravaApp> & { id: number }) =>
      apiPatch<AdminStravaApp>(`/api/v1/admin/strava-apps/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'strava-apps'] })
      qc.invalidateQueries({ queryKey: ['admin', 'metrics'] })
    },
  })
}

// ── Users ─────────────────────────────────────────────────────────────────────

export function useAdminUsers(params: { limit?: number; offset?: number; search?: string }) {
  const { limit = 25, offset = 0, search } = params
  return useQuery<AdminUsersPage>({
    queryKey: ['admin', 'users', limit, offset, search ?? ''],
    queryFn: () =>
      apiGet<AdminUsersPage>(
        `/api/v1/admin/users?limit=${limit}&offset=${offset}` +
          (search ? `&search=${encodeURIComponent(search)}` : ''),
      ),
    staleTime: 15_000,
  })
}

export function useAdminUserDetail(userId: string | null) {
  return useQuery<AdminUserDetail>({
    queryKey: ['admin', 'users', userId],
    queryFn: () => apiGet<AdminUserDetail>(`/api/v1/admin/users/${userId}`),
    enabled: !!userId,
    staleTime: 15_000,
  })
}
