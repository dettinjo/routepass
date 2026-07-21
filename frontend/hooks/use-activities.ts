'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiGet, apiPost } from '@/lib/api'
import type {
  ActivitiesResponse,
  ActivityFilters,
  ActivityOverview,
  ImportResult,
  SeedResult,
} from '@/types/api'

/**
 * Fire-and-forget sync trigger.  Enqueues a background poll for all connected
 * sources, then invalidates the activities list after a short delay so the UI
 * reflects newly ingested activities without an explicit user action.
 *
 * The delay (5 s) gives the worker time to process a typical sync run.
 * The function is idempotent on the backend — calling it multiple times in
 * quick succession is safe; ARQ deduplicates enqueued jobs by function+args.
 */
export function useTriggerSync() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost('/api/v1/sync/trigger'),
    onSuccess: () => {
      // Invalidate sync status immediately so the "last synced" label updates
      qc.invalidateQueries({ queryKey: ['sync'] })
      // Refresh the activity list once the worker has had time to finish
      setTimeout(() => qc.invalidateQueries({ queryKey: ['activities'] }), 5_000)
    },
  })
}

interface UseActivitiesParams {
  skip?: number
  limit?: number
  filters?: ActivityFilters
}

function buildActivityQs(skip: number, limit: number, filters: ActivityFilters = {}): string {
  const params = new URLSearchParams()
  params.set('skip', String(skip))
  params.set('limit', String(limit))
  if (filters.source)                    params.set('source', filters.source)
  if (filters.sync_status)               params.set('sync_status', filters.sync_status)
  if (filters.sport_type)                params.set('sport_type', filters.sport_type)
  if (filters.search)                    params.set('search', filters.search)
  if (filters.synced !== undefined)      params.set('synced', String(filters.synced))
  if (filters.date_from)                 params.set('date_from', filters.date_from)
  if (filters.date_to)                   params.set('date_to', filters.date_to)
  return params.toString()
}

function buildFilterQs(filters: ActivityFilters = {}): string {
  const params = new URLSearchParams()
  if (filters.source)                    params.set('source', filters.source)
  if (filters.sync_status)               params.set('sync_status', filters.sync_status)
  if (filters.sport_type)                params.set('sport_type', filters.sport_type)
  if (filters.search)                    params.set('search', filters.search)
  if (filters.synced !== undefined)      params.set('synced', String(filters.synced))
  if (filters.date_from)                 params.set('date_from', filters.date_from)
  if (filters.date_to)                   params.set('date_to', filters.date_to)
  return params.toString()
}

export function useActivities({ skip = 0, limit = 50, filters = {} }: UseActivitiesParams = {}) {
  return useQuery<ActivitiesResponse>({
    queryKey: ['activities', { skip, limit, ...filters }],
    queryFn: () => apiGet(`/api/v1/activities?${buildActivityQs(skip, limit, filters)}`),
  })
}

/** Aggregate stats over all activities matching the current filters. */
export function useActivitiesOverview(filters: ActivityFilters, enabled = true) {
  return useQuery<ActivityOverview>({
    queryKey: ['activities-overview', filters],
    queryFn: () => apiGet(`/api/v1/activities/overview?${buildFilterQs(filters)}`),
    enabled,
    staleTime: 30_000,
  })
}

/** Fetch all IDs matching the current filters (max 500) for bulk selection. */
export function useActivityIds(filters: ActivityFilters, enabled: boolean) {
  return useQuery<{ ids: string[]; count: number }>({
    queryKey: ['activity-ids', filters],
    queryFn: () => apiGet(`/api/v1/activities/ids?${buildFilterQs(filters)}`),
    enabled,
    staleTime: 0,  // always fresh when triggered
  })
}

export function useSyncActivity() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, destination }: { id: string; destination?: string }) =>
      apiPost<{ status: string; message: string }>(`/api/v1/activities/${id}/sync`, {
        destination: destination ?? null,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['activities'] }),
  })
}

export function useDeleteActivity() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (activityId: string) => apiDelete(`/api/v1/activities/${activityId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['activities'] }),
  })
}

export function useBulkSyncActivities() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ ids, destination }: { ids: string[]; destination?: string }) => {
      const results: Array<{ id: string; status: string; message: string }> = []
      for (const id of ids) {
        const res = await apiPost<{ status: string; message: string }>(
          `/api/v1/activities/${id}/sync`,
          { destination: destination ?? null },
        )
        results.push({ id, ...res })
      }
      return results
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['activities'] }),
  })
}

export function useSeedActivities() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost<SeedResult>('/api/v1/activities/seed', {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['activities'] }),
  })
}

export function useClearSeedActivities() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiDelete<{ deleted: number }>('/api/v1/activities/seed/clear'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['activities'] }),
  })
}

export function useImportGpx() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ files, names }: { files: FileList | File[]; names?: string[] }) => {
      const form = new FormData()
      Array.from(files).forEach((f) => form.append('files', f))
      if (names && names.length > 0) {
        form.append('names', JSON.stringify(names))
      }
      const res = await fetch('/api/v1/activities/import', {
        method: 'POST',
        headers: { Authorization: `Bearer ${(await import('@/store/auth')).useAuthStore.getState().token ?? ''}` },
        body: form,
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
        throw new Error(err.detail ?? 'Upload failed')
      }
      return res.json() as Promise<ImportResult>
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['activities'] }),
  })
}
