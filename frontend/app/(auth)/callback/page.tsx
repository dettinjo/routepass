'use client'

import { Suspense, useEffect, useRef } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Loader2 } from 'lucide-react'
import { useAuthStore } from '@/store/auth'
import type { UserMe } from '@/types/api'

// useSearchParams() must live inside a Suspense boundary when output:'standalone'
// is enabled. We split it into a child component so the outer page can wrap it.
function CallbackInner() {
  const router = useRouter()
  const params = useSearchParams()
  const login  = useAuthStore((s) => s.login)
  const done   = useRef(false)

  useEffect(() => {
    if (done.current) return
    done.current = true

    const token = params.get('token')
    if (!token) {
      router.replace('/login?error=oauth_failed')
      return
    }

    fetch('/api/v1/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => {
        if (!r.ok) throw new Error('Failed to fetch user profile')
        return r.json() as Promise<UserMe>
      })
      .then((user) => {
        login(token, user)
        router.replace('/dashboard')
      })
      .catch(() => {
        router.replace('/login?error=oauth_failed')
      })
  }, [params, router, login])

  return null
}

function Spinner() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-text-secondary">
      <Loader2 className="w-6 h-6 animate-spin" />
      <p className="text-body-sm">Completing sign-in…</p>
    </div>
  )
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <Spinner />
      <CallbackInner />
    </Suspense>
  )
}
