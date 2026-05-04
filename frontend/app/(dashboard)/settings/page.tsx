'use client'

import { useState } from 'react'
import { AlertTriangle, Loader2, Save } from 'lucide-react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useAuthStore } from '@/store/auth'
import { useUser } from '@/hooks/use-user'
import { apiPatch, apiPost } from '@/lib/api'
import { useRouter } from 'next/navigation'

// ── Sync preferences form ──────────────────────────────────────────────────────

function SyncPreferencesCard() {
  const { data: user, refetch } = useUser()
  const authUser = useAuthStore((s) => s.user)
  const isPro = authUser?.tier === 'pro'

  const [komootToStrava, setKomootToStrava] = useState<boolean>(
    user?.sync_komoot_to_strava ?? true,
  )
  const [pollInterval, setPollInterval] = useState<number>(
    user?.komoot_poll_interval_min ?? 120,
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const minInterval = isPro ? 10 : 120

  async function save() {
    setSaving(true)
    setError(null)
    try {
      await apiPatch('/api/v1/auth/me/settings', {
        sync_komoot_to_strava: komootToStrava,
        komoot_poll_interval_min: pollInterval,
      })
      await refetch()
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sync preferences</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Sync direction toggle */}
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-body text-text-primary">Komoot → Strava sync</p>
            <p className="text-caption text-text-secondary">
              Automatically push new Komoot tours to Strava.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={komootToStrava}
            onClick={() => setKomootToStrava((v) => !v)}
            className={`relative inline-flex h-6 w-11 flex-shrink-0 rounded-full border-2 border-transparent
              transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2
              ${komootToStrava ? 'bg-primary' : 'bg-border-strong'}`}
          >
            <span
              className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow
                transition duration-200 ${komootToStrava ? 'translate-x-5' : 'translate-x-0'}`}
            />
          </button>
        </div>

        {/* Poll interval */}
        <div>
          <div className="flex items-center gap-2 mb-1">
            <p className="text-body text-text-primary">Poll interval</p>
            {!isPro && <Badge variant="pro">Pro</Badge>}
          </div>
          <p className="text-caption text-text-secondary mb-2">
            How often RoutePass checks Komoot for new tours.
            {!isPro && ' Upgrade to Pro for intervals below 120 minutes.'}
          </p>
          <div className="flex items-center gap-3">
            <input
              type="number"
              min={minInterval}
              max={1440}
              step={isPro ? 10 : 30}
              value={pollInterval}
              onChange={(e) => setPollInterval(parseInt(e.target.value, 10))}
              className="w-24 h-9 px-3 text-body bg-surface-raised border border-border rounded-md
                         text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
            />
            <span className="text-body-sm text-text-secondary">minutes</span>
          </div>
        </div>

        {error && (
          <p className="text-body-sm text-error">{error}</p>
        )}

        <Button
          variant="secondary"
          size="sm"
          loading={saving}
          onClick={save}
        >
          {saved ? '✓ Saved' : <><Save className="w-4 h-4" /> Save preferences</>}
        </Button>
      </CardContent>
    </Card>
  )
}

// ── Profile card ───────────────────────────────────────────────────────────────

function ProfileCard() {
  const user    = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)

  const [name, setName]     = useState(user?.name ?? '')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved]   = useState(false)
  const [error, setError]   = useState<string | null>(null)

  async function saveName() {
    setSaving(true)
    setError(null)
    try {
      await apiPatch('/api/v1/auth/me/settings', { name })
      if (user) setUser({ ...user, name: name || null })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Name */}
        <div>
          <label className="block text-label text-text-secondary mb-1" htmlFor="profile-name">
            Display name
          </label>
          <div className="flex gap-2">
            <input
              id="profile-name"
              type="text"
              autoComplete="name"
              placeholder="Your name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="flex-1 h-9 px-3 text-body bg-surface-raised border border-border rounded-md
                         text-text-primary placeholder:text-text-disabled
                         focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent"
            />
            <Button variant="secondary" size="sm" loading={saving} onClick={saveName}>
              {saved ? '✓' : <Save className="w-4 h-4" />}
            </Button>
          </div>
          {error && <p className="text-body-sm text-error mt-1">{error}</p>}
        </div>
        <div>
          <p className="text-label text-text-secondary mb-1">Email</p>
          <p className="text-body text-text-primary">{user?.email ?? '—'}</p>
        </div>
        <div>
          <p className="text-label text-text-secondary mb-1">Plan</p>
          <p className="text-body text-text-primary capitalize flex items-center gap-2">
            {user?.tier ?? 'free'}
            {user?.tier === 'pro' && <Badge variant="pro">Pro</Badge>}
          </p>
        </div>
        <p className="text-caption text-text-disabled">
          To change your email or password, contact support.
        </p>
      </CardContent>
    </Card>
  )
}

// ── Danger zone ────────────────────────────────────────────────────────────────

function DangerZoneCard() {
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const logout = useAuthStore((s) => s.logout)
  const router = useRouter()

  async function deleteAccount() {
    setDeleting(true)
    setError(null)
    try {
      await apiPost('/api/v1/auth/me/delete')
      logout()
      router.push('/')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete account')
      setDeleting(false)
    }
  }

  return (
    <Card className="border-error">
      <CardHeader>
        <CardTitle className="text-error">Danger zone</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-body-sm text-text-secondary">
          Permanently delete your account and all associated data — connections, pipelines,
          activity history. This cannot be undone.
        </p>
        {!confirming ? (
          <Button variant="danger" size="sm" onClick={() => setConfirming(true)}>
            <AlertTriangle className="w-4 h-4" />
            Delete account
          </Button>
        ) : (
          <div className="space-y-3 p-3 rounded-md bg-error-light border border-error">
            <p className="text-body-sm text-error font-medium">
              Are you absolutely sure? This will delete all your data permanently.
            </p>
            {error && <p className="text-caption text-error">{error}</p>}
            <div className="flex gap-2">
              <Button variant="danger" size="sm" loading={deleting} onClick={deleteAccount}>
                {deleting ? 'Deleting…' : 'Yes, delete everything'}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-heading-xl text-text-primary">Settings</h1>
        <p className="text-body text-text-secondary mt-1">
          Manage your account and sync preferences.
        </p>
      </div>

      <div className="space-y-4 max-w-xl">
        <ProfileCard />
        <SyncPreferencesCard />
        <DangerZoneCard />
      </div>
    </div>
  )
}
