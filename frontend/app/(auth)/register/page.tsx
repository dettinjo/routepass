'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { CheckCircle2, ArrowRight, Loader2 } from 'lucide-react'
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui'
import { Button } from '@/components/ui'
import { Input, FormField } from '@/components/ui'
import { Alert } from '@/components/ui'
import { useAuthStore } from '@/store/auth'
import type { TokenResponse, UserMe } from '@/types/api'
import { GoogleIcon, GitHubIcon } from '@/components/platform-icons'

// ── Step indicator ─────────────────────────────────────────────────────────────

function StepDots({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center justify-center gap-2 mb-6">
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          className={`h-1.5 rounded-full transition-all ${
            i < current
              ? 'w-4 bg-primary'
              : i === current
              ? 'w-6 bg-primary'
              : 'w-4 bg-border'
          }`}
        />
      ))}
    </div>
  )
}

// ── Step 1: Account ────────────────────────────────────────────────────────────

interface Step1Props {
  onNext: (email: string, password: string) => void
  loading: boolean
  error: string | null
}

function Step1Account({ onNext, loading, error }: Step1Props) {
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm]   = useState('')
  const [errors, setErrors]     = useState<Record<string, string>>({})

  function validate() {
    const e: Record<string, string> = {}
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) e.email = 'Enter a valid email address'
    if (password.length < 8) e.password = 'Minimum 8 characters'
    if (password !== confirm) e.confirm = 'Passwords do not match'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault()
    if (validate()) onNext(email, password)
  }

  return (
    <>
      <p className="text-body-sm text-text-secondary text-center mb-5">
        Or sign up with email below
      </p>

      {/* Social providers */}
      <div className="grid grid-cols-2 gap-2 mb-5">
        <a
          href="/api/v1/auth/google"
          className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-md border border-border bg-surface hover:bg-surface-raised transition-colors text-body-sm font-medium text-text-primary"
        >
          <GoogleIcon size={18} />
          <span>Google</span>
        </a>
        <a
          href="/api/v1/auth/github"
          className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-md border border-border bg-surface hover:bg-surface-raised transition-colors text-body-sm font-medium text-text-primary"
        >
          <GitHubIcon size={18} mono />
          <span>GitHub</span>
        </a>
      </div>

      <div className="flex items-center gap-3 mb-5">
        <div className="flex-1 h-px bg-border" />
        <span className="text-caption text-text-disabled">or</span>
        <div className="flex-1 h-px bg-border" />
      </div>

      {error && <Alert variant="error" className="mb-4">{error}</Alert>}

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <FormField label="Email" htmlFor="email" required error={errors.email}>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            error={!!errors.email}
          />
        </FormField>

        <FormField label="Password" htmlFor="password" required error={errors.password} hint="Minimum 8 characters">
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={!!errors.password}
          />
        </FormField>

        <FormField label="Confirm password" htmlFor="confirm" required error={errors.confirm}>
          <Input
            id="confirm"
            type="password"
            autoComplete="new-password"
            placeholder="••••••••"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            error={!!errors.confirm}
          />
        </FormField>

        <Button type="submit" className="w-full" loading={loading}>
          Continue
          {!loading && <ArrowRight className="w-4 h-4 ml-1" />}
        </Button>
      </form>
    </>
  )
}

// ── Step 2: Name ───────────────────────────────────────────────────────────────

interface Step2Props {
  onNext: (name: string) => void
  onSkip: () => void
  loading: boolean
  error: string | null
}

function Step2Name({ onNext, onSkip, loading, error }: Step2Props) {
  const [name, setName] = useState('')

  function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault()
    onNext(name.trim())
  }

  return (
    <>
      <p className="text-body text-text-secondary text-center mb-6">
        What should we call you?
      </p>

      {error && <Alert variant="error" className="mb-4">{error}</Alert>}

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <Input
          id="name"
          type="text"
          autoComplete="name"
          autoFocus
          placeholder="Your name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />

        <Button type="submit" className="w-full" loading={loading}>
          Continue
          {!loading && <ArrowRight className="w-4 h-4 ml-1" />}
        </Button>
      </form>

      <button
        type="button"
        onClick={onSkip}
        className="mt-3 w-full text-body-sm text-text-secondary hover:text-text-primary transition-colors"
      >
        Skip for now
      </button>
    </>
  )
}

// ── Step 3: Done ───────────────────────────────────────────────────────────────

function Step3Done({ name }: { name: string }) {
  return (
    <div className="flex flex-col items-center gap-4 text-center py-4">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-success/10">
        <CheckCircle2 className="h-8 w-8 text-success" />
      </div>
      <div>
        <p className="text-heading-sm text-text-primary font-semibold">
          {name ? `Welcome, ${name}!` : 'Account created!'}
        </p>
        <p className="text-body-sm text-text-secondary mt-1">
          Taking you to your dashboard…
        </p>
      </div>
      <Loader2 className="h-5 w-5 animate-spin text-text-disabled mt-2" />
    </div>
  )
}

// ── Page shell ─────────────────────────────────────────────────────────────────

export default function RegisterPage() {
  const router = useRouter()
  const loginStore = useAuthStore((s) => s.login)

  const [step, setStep]         = useState<1 | 2 | 3>(1)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState<string | null>(null)

  // Stored between steps
  const [accessToken, setAccessToken] = useState('')
  const [savedName, setSavedName]     = useState('')

  // ── Step 1 handler: create account + get token ─────────────────────────────
  async function handleAccountStep(email: string, password: string) {
    setLoading(true)
    setError(null)
    try {
      const registerRes = await fetch('/api/v1/auth/register', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ email, password }),
      })
      if (!registerRes.ok) {
        const err = await registerRes.json()
        const detail = Array.isArray(err.detail) ? (err.detail[0]?.msg ?? 'Registration failed') : (err.detail ?? 'Registration failed')
        throw new Error(String(detail))
      }

      const tokenRes = await fetch('/api/v1/auth/login', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ email, password }),
      })
      if (!tokenRes.ok) throw new Error('Login after registration failed')
      const { access_token } = (await tokenRes.json()) as TokenResponse

      setAccessToken(access_token)
      setStep(2)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed. Try again.')
    } finally {
      setLoading(false)
    }
  }

  // ── Step 2 handler: save name, then finish ─────────────────────────────────
  async function handleNameStep(name: string) {
    setSavedName(name)
    setLoading(true)
    setError(null)
    try {
      if (name) {
        // PATCH name and fetch updated profile
        await fetch('/api/v1/auth/me/settings', {
          method:  'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
          body:    JSON.stringify({ name }),
        })
      }
      await finishOnboarding(name)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save name. Try again.')
      setLoading(false)
    }
  }

  async function finishOnboarding(name: string) {
    const meRes = await fetch('/api/v1/auth/me', {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
    if (!meRes.ok) throw new Error('Failed to load user profile')
    const me = (await meRes.json()) as UserMe

    loginStore(accessToken, me)
    setSavedName(name)
    setStep(3)
    setTimeout(() => router.push('/dashboard'), 1800)
  }

  const stepTitles = ['Create your account', 'What\'s your name?', 'You\'re all set']

  return (
    <Card>
      <CardHeader>
        <CardTitle>{stepTitles[step - 1]}</CardTitle>
      </CardHeader>
      <CardContent>
        <StepDots current={step - 1} total={3} />

        {step === 1 && (
          <Step1Account onNext={handleAccountStep} loading={loading} error={error} />
        )}
        {step === 2 && (
          <Step2Name
            onNext={handleNameStep}
            onSkip={() => handleNameStep('')}
            loading={loading}
            error={error}
          />
        )}
        {step === 3 && (
          <Step3Done name={savedName} />
        )}
      </CardContent>

      {step === 1 && (
        <CardFooter className="justify-center">
          <p className="text-body-sm text-text-secondary">
            Already have an account?{' '}
            <Link href="/login" className="text-primary hover:underline">
              Sign in
            </Link>
          </p>
        </CardFooter>
      )}
    </Card>
  )
}
