'use client'

import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api'
import type { ActivityMetrics, ActivityTrack } from '@/types/api'

export function useActivityMetrics(activityId: string | null, enabled = true) {
  return useQuery<ActivityMetrics>({
    queryKey: ['activity', activityId, 'metrics'],
    queryFn: () => apiGet<ActivityMetrics>(`/api/v1/activities/${activityId}/metrics`),
    enabled: !!activityId && enabled,
    staleTime: 60_000,
    // While the backfill cron is still computing, poll so the panel fills in.
    refetchInterval: (query) => (query.state.data?.computed ? false : 20_000),
  })
}

export function useActivityTrack(activityId: string | null, enabled = true) {
  return useQuery<ActivityTrack>({
    queryKey: ['activity', activityId, 'track'],
    queryFn: () => apiGet<ActivityTrack>(`/api/v1/activities/${activityId}/track`),
    enabled: !!activityId && enabled,
    staleTime: 60_000,
    refetchInterval: (query) => (query.state.data?.computed ? false : 20_000),
  })
}
