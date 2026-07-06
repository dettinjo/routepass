'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiPatch, apiPost, apiGet } from '@/lib/api'
import type { Pipeline } from '@/types/api'

export function usePipelines() {
  return useQuery<Pipeline[]>({
    queryKey: ['pipelines'],
    queryFn: () => apiGet<Pipeline[]>('/api/v1/pipelines'),
    staleTime: 30_000,
  })
}

export function useCreatePipeline() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      source_connection_id: string
      dest_connection_id: string
      name: string
      enabled?: boolean
    }) => apiPost<Pipeline>('/api/v1/pipelines', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pipelines'] }),
  })
}

export function useUpdatePipeline() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; name?: string; enabled?: boolean }) =>
      apiPatch<Pipeline>(`/api/v1/pipelines/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pipelines'] }),
  })
}

export function useDeletePipeline() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/v1/pipelines/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pipelines'] }),
  })
}

export function useTriggerPipelineSync() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiPost(`/api/v1/pipelines/${id}/sync`),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ['activities'] }), 2000),
  })
}
