'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiPost, apiPut, apiGet } from '@/lib/api'
import type { SyncRule } from '@/types/api'

interface RulesResponse {
  data: SyncRule[]
}

export function useRules() {
  return useQuery<RulesResponse>({
    queryKey: ['rules'],
    queryFn: () => apiGet<RulesResponse>('/api/v1/rules'),
    staleTime: 30_000,
  })
}

export function useCreateRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      name: string
      direction: string
      conditions: Record<string, unknown>
      actions: Record<string, unknown>
      rule_order?: number
      is_active?: boolean
    }) => apiPost('/api/v1/rules', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['rules'] }),
  })
}

export function useUpdateRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: string
      name: string
      direction: string
      conditions: Record<string, unknown>
      actions: Record<string, unknown>
      rule_order?: number
      is_active?: boolean
    }) => apiPut(`/api/v1/rules/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['rules'] }),
  })
}

export function useDeleteRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/v1/rules/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['rules'] }),
  })
}
