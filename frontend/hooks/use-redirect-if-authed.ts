'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/store/auth'

/**
 * Redirects an already-authenticated visitor away from public pages (landing,
 * login, register) to the dashboard. Returns true whenever the public page
 * should NOT be rendered yet — either because the session-restore check is
 * still in flight (we don't know yet) or because a session was found and the
 * redirect is in flight. This prevents the public page from flashing before an
 * active session gets bounced to the dashboard: callers render a placeholder
 * while this is true and the real public content only once it's false.
 */
export function useRedirectIfAuthed(to = '/dashboard'): boolean {
  const router = useRouter()
  const initialized = useAuthStore((s) => s.initialized)
  const token = useAuthStore((s) => s.token)

  const authed = initialized && !!token
  const hidePublicContent = !initialized || authed

  useEffect(() => {
    if (authed) router.replace(to)
  }, [authed, router, to])

  return hidePublicContent
}
