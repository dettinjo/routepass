'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/store/auth'

/**
 * Redirects an already-authenticated visitor away from public pages (landing,
 * login, register) to the dashboard, once the session-restore attempt has
 * finished. Returns true while a redirect is pending so callers can render a
 * placeholder instead of flashing the public page.
 */
export function useRedirectIfAuthed(to = '/dashboard'): boolean {
  const router = useRouter()
  const initialized = useAuthStore((s) => s.initialized)
  const token = useAuthStore((s) => s.token)

  const redirecting = initialized && !!token

  useEffect(() => {
    if (redirecting) router.replace(to)
  }, [redirecting, router, to])

  return redirecting
}
