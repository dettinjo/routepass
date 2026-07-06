'use client'

import { useEffect, useRef, useState, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Loader2, CheckCircle2, AlertCircle } from 'lucide-react'

// ── Inner component (needs Suspense because it uses useSearchParams) ──────────

function StravaCallbackInner() {
  const router   = useRouter()
  const params   = useSearchParams()
  const posted   = useRef(false)

  const [status, setStatus] = useState<'waiting' | 'connecting' | 'success' | 'error'>('waiting')
  const [message, setMessage] = useState<string>('Connecting your Strava account…')

  useEffect(() => {
    // Strava denied the request
    const stravaError = params.get('error')
    if (stravaError) {
      setStatus('error')
      setMessage('Strava authorisation was denied. Please try again.')
      return
    }

    const code = params.get('code')
    if (!code) {
      setStatus('error')
      setMessage('No authorisation code received from Strava.')
      return
    }

    // The `state` param is the short-lived JWT our backend embedded when it
    // built the Strava auth URL. Use it directly — no need to wait for the
    // cookie-based AuthInitializer to restore the session.
    const stateToken = params.get('state')
    if (!stateToken) {
      setStatus('error')
      setMessage('Missing state token. Please try connecting again.')
      return
    }

    // Guard against double-posting on React strict-mode double-invoke
    if (posted.current) return
    posted.current = true

    setStatus('connecting')

    fetch('/api/v1/auth/strava/callback', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${stateToken}`,
      },
      body: JSON.stringify({ code }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const text = await res.text().catch(() => '')
          let detail = `Server error ${res.status}`
          try { detail = JSON.parse(text).detail ?? detail } catch { /* non-JSON body */ }
          throw new Error(detail)
        }
        return res.json()
      })
      .then(() => {
        setStatus('success')
        setMessage('Strava connected! Redirecting…')
        setTimeout(() => router.push('/connections'), 1500)
      })
      .catch((err: Error) => {
        setStatus('error')
        setMessage(err.message)
        posted.current = false
      })
  }, [params, router])

  return (
    <div className="flex flex-col items-center gap-4 text-center">
      {status === 'waiting' || status === 'connecting' ? (
        <>
          <Loader2 className="h-10 w-10 animate-spin text-primary" />
          <p className="text-body text-text-secondary">{message}</p>
        </>
      ) : status === 'success' ? (
        <>
          <CheckCircle2 className="h-10 w-10 text-success" />
          <p className="text-body text-text-primary font-medium">{message}</p>
        </>
      ) : (
        <>
          <AlertCircle className="h-10 w-10 text-error" />
          <p className="text-body text-error font-medium">{message}</p>
          <button
            onClick={() => router.push('/connections')}
            className="text-body-sm text-primary hover:underline"
          >
            Back to Connections
          </button>
        </>
      )}
    </div>
  )
}

// ── Page shell ────────────────────────────────────────────────────────────────

export default function StravaCallbackPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg">
      <div className="w-full max-w-sm p-8">
        <Suspense
          fallback={
            <div className="flex flex-col items-center gap-4">
              <Loader2 className="h-10 w-10 animate-spin text-primary" />
              <p className="text-body text-text-secondary">Loading…</p>
            </div>
          }
        >
          <StravaCallbackInner />
        </Suspense>
      </div>
    </div>
  )
}
