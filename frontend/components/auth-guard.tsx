'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Loader2 } from 'lucide-react'
import { useAuthStore } from '@/store/auth'

/**
 * Wraps all dashboard pages. Waits for AuthInitializer to finish restoring the
 * session (initialized=true) before deciding whether to redirect to /login.
 *
 * While not initialized, renders a centred spinner instead of the page — this
 * prevents dashboard child components from mounting and firing React Query calls
 * with token=null, which would trigger the 401 → redirect race condition.
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const initialized = useAuthStore((s) => s.initialized)
  const token = useAuthStore((s) => s.token)
  const router = useRouter()

  useEffect(() => {
    if (!initialized) return
    if (!token) router.replace('/login')
  }, [initialized, token, router])

  if (!initialized) {
    return (
      <div className="min-h-screen bg-bg flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-text-disabled" />
      </div>
    )
  }

  if (!token) return null  // redirect in flight

  return <>{children}</>
}
