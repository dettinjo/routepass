'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '@/lib/api'

export interface SyncStatusResponse {
  komoot_connected: boolean
  strava_connected: boolean
  sync_komoot_to_strava: boolean
  sync_strava_to_komoot: boolean
  last_komoot_sync_at: string | null
  last_strava_sync_at: string | null
  last_successful_sync_at: string | null
  total_synced_count: number
  last_error: string | null
  last_error_at: string | null
  latest_activity: {
    id: string
    activity_name: string | null
    sport_type: string | null
    distance_m: number | null
    synced_at: string
    sync_status: string
  } | null
}

export function useSyncStatus() {
  return useQuery<SyncStatusResponse>({
    queryKey: ['sync', 'status'],
    queryFn: () => apiGet<SyncStatusResponse>('/api/v1/sync/status'),
    staleTime: 15_000,
    refetchInterval: 60_000,
  })
}

export function useTriggerSync() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost('/api/v1/sync/trigger'),
    onSuccess: () => {
      setTimeout(() => qc.invalidateQueries({ queryKey: ['sync'] }), 2000)
    },
  })
}
