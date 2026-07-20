'use client'

import { useMutation, useQuery } from '@tanstack/react-query'
import { apiGet, apiPost } from '@/lib/api'
import type { BillingSubscription } from '@/types/api'

export function useBillingSubscription() {
  return useQuery<BillingSubscription>({
    queryKey: ['billing', 'subscription'],
    queryFn: () => apiGet<BillingSubscription>('/api/v1/billing/subscription'),
    staleTime: 60_000,
  })
}

export type PlanId = 'pro_monthly' | 'pro_annual' | 'lifetime'

export function useCheckout() {
  return useMutation({
    mutationFn: (plan: PlanId) =>
      apiPost<{ url: string }>('/api/v1/billing/checkout', { plan }),
    onSuccess: ({ url }) => {
      window.location.href = url
    },
  })
}

export function useBillingPortal() {
  return useMutation({
    mutationFn: () => apiPost<{ url: string }>('/api/v1/billing/portal'),
    onSuccess: ({ url }) => {
      window.location.href = url
    },
  })
}
