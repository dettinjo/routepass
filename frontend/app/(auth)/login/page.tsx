'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui'
import { Button } from '@/components/ui'
import { Input, FormField } from '@/components/ui'
import { Alert } from '@/components/ui'
import { apiPost } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { useRedirectIfAuthed } from '@/hooks/use-redirect-if-authed'
import type { TokenResponse, UserMe } from '@/types/api'
import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { GoogleIcon, GitHubIcon } from '@/components/platform-icons'

const schema = z.object({
  email:    z.string().email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
})

type FormData = z.infer<typeof schema>

function SocialDivider() {
  return (
    <div className="flex items-center gap-3 my-5">
      <div className="flex-1 h-px bg-border" />
      <span className="text-caption text-text-disabled">or continue with</span>
      <div className="flex-1 h-px bg-border" />
    </div>
  )
}

export default function LoginPage() {
  const router = useRouter()
  const login  = useAuthStore((s) => s.login)
  const redirecting = useRedirectIfAuthed()
  const [serverError, setServerError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(schema) })

  async function onSubmit(data: FormData) {
    setServerError(null)
    try {
      const tokenRes = await fetch('/api/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email: data.email, password: data.password }),
        headers: { 'Content-Type': 'application/json' },
      })
      if (!tokenRes.ok) {
        const err = await tokenRes.json()
        // FastAPI validation errors return detail as an array of objects
        const detail = Array.isArray(err.detail)
          ? (err.detail[0]?.msg ?? 'Login failed')
          : (err.detail ?? 'Login failed')
        throw new Error(String(detail))
      }
      const { access_token } = (await tokenRes.json()) as TokenResponse

      const meRes = await fetch('/api/v1/auth/me', {
        headers: { Authorization: `Bearer ${access_token}` },
      })
      if (!meRes.ok) throw new Error('Failed to load user profile')
      const me = (await meRes.json()) as UserMe

      login(access_token, me)  // login() now sets the cookie too
      router.push('/dashboard')
    } catch (err) {
      setServerError(err instanceof Error ? err.message : 'Login failed. Try again.')
    }
  }

  if (redirecting) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="w-6 h-6 animate-spin text-text-disabled" />
      </div>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sign in to RoutePass</CardTitle>
      </CardHeader>
      <CardContent>
        {serverError && (
          <Alert variant="error" className="mb-5">
            {serverError}
          </Alert>
        )}

        {/* Social auth providers */}
        <div className="grid grid-cols-2 gap-2">
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

        <SocialDivider />

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <FormField label="Email" htmlFor="email" required error={errors.email?.message}>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              error={!!errors.email}
              {...register('email')}
            />
          </FormField>

          <FormField label="Password" htmlFor="password" required error={errors.password?.message}>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              placeholder="••••••••"
              error={!!errors.password}
              {...register('password')}
            />
          </FormField>

          <Button type="submit" className="w-full" loading={isSubmitting}>
            Sign in
          </Button>
        </form>
      </CardContent>
      <CardFooter className="justify-center">
        <p className="text-body-sm text-text-secondary">
          No account?{' '}
          <Link href="/register" className="text-primary hover:underline">
            Sign up free
          </Link>
        </p>
      </CardFooter>
    </Card>
  )
}
