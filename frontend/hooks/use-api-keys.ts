'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiDelete, apiPost, apiGet } from '@/lib/api'
import type { ApiKey, ApiKeyCreated } from '@/types/api'

interface ApiKeysResponse {
  data: ApiKey[]
}

export function useApiKeys() {
  return useQuery<ApiKeysResponse>({
    queryKey: ['api-keys'],
    queryFn: () => apiGet<ApiKeysResponse>('/api/v1/api-keys'),
    staleTime: 30_000,
  })
}

export function useCreateApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      apiPost<ApiKeyCreated>('/api/v1/api-keys', { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['api-keys'] }),
  })
}

export function useRevokeApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/v1/api-keys/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['api-keys'] }),
  })
}
