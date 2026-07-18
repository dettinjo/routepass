'use client'

// Top-level provider tree.
// Add new providers here — never scatter them across layout files.

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState, useEffect } from 'react'
import { useAuthStore } from '@/store/auth'
import type { UserMe } from '@/types/api'

function AuthInitializer() {
  const { token, initialized, login, setInitialized } = useAuthStore()

  useEffect(() => {
    // Already restored — nothing to do
    if (initialized) return
    // Token already in memory (e.g. login happened in this tab)
    if (token) { setInitialized(); return }

    const match = document.cookie.match(/(?:^|;\s*)rp_token=([^;]+)/)
    const savedToken = match?.[1]

    if (!savedToken) {
      // No cookie → no session to restore; mark initialized so guards can act
      setInitialized()
      return
    }

    fetch('/api/v1/auth/me', {
      headers: { Authorization: `Bearer ${savedToken}` },
    })
      .then((r) => (r.ok ? (r.json() as Promise<UserMe>) : Promise.reject()))
      .then(async (me) => {
        // Roll the JWT forward so the 30-day window slides on every visit. If
        // refresh fails for any reason, fall back to the still-valid saved token.
        let freshToken = savedToken
        try {
          const refreshed = await fetch('/api/v1/auth/refresh', {
            method: 'POST',
            headers: { Authorization: `Bearer ${savedToken}` },
          })
          if (refreshed.ok) {
            freshToken = ((await refreshed.json()) as { access_token: string }).access_token
          }
        } catch {
          /* keep savedToken */
        }
        login(freshToken, me)   // login() re-writes the cookie + sets initialized=true
      })
      .catch(() => {
        // Token expired or invalid — clear the stale cookie and mark initialized
        document.cookie = 'rp_token=; path=/; SameSite=Lax; max-age=0'
        setInitialized()
      })
  // Only run once on mount — deps intentionally omitted to avoid infinite loops
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return null
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  )

  return (
    <QueryClientProvider client={queryClient}>
      <AuthInitializer />
      {children}
    </QueryClientProvider>
  )
}
