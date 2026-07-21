'use client'

import { useState } from 'react'
import { AlertTriangle, Save } from 'lucide-react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useAuthStore } from '@/store/auth'
import { apiPatch, apiPost } from '@/lib/api'
import { useRouter } from 'next/navigation'

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
            {user && user.tier !== 'free' && <Badge variant="pro">Pro</Badge>}
          </p>
        </div>
        <p className="text-caption text-text-disabled">
          To change your email or password, contact support.
        </p>
      </CardContent>
    </Card>
  )
}

// ── Training profile card ────────────────────────────────────────────────────────

function TrainingProfileCard() {
  const user    = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)

  const [ftp, setFtp]       = useState(user?.ftp != null ? String(user.ftp) : '')
  const [hrMax, setHrMax]   = useState(user?.hr_max != null ? String(user.hr_max) : '')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved]   = useState(false)
  const [error, setError]   = useState<string | null>(null)

  async function save() {
    setSaving(true)
    setError(null)
    try {
      // Empty string clears the value; backend treats -1 as "unset".
      const ftpVal   = ftp.trim() === '' ? -1 : parseInt(ftp, 10)
      const hrMaxVal = hrMax.trim() === '' ? -1 : parseInt(hrMax, 10)
      if (Number.isNaN(ftpVal) || Number.isNaN(hrMaxVal)) {
        setError('Enter whole numbers only.')
        return
      }
      const res = await apiPatch<{ ftp: number | null; hr_max: number | null }>(
        '/api/v1/auth/me/settings',
        { ftp: ftpVal, hr_max: hrMaxVal },
      )
      if (user) setUser({ ...user, ftp: res.ftp, hr_max: res.hr_max })
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
        <CardTitle>Training profile</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-body-sm text-text-secondary">
          Set these to unlock Training Stress Score (TSS) and accurate power &
          heart-rate zones in your activity analysis. Changing them recomputes
          affected activities in the background.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-label text-text-secondary mb-1" htmlFor="profile-ftp">
              FTP <span className="text-text-disabled">(watts)</span>
            </label>
            <input
              id="profile-ftp"
              type="number"
              inputMode="numeric"
              min={1}
              max={2000}
              placeholder="e.g. 250"
              value={ftp}
              onChange={(e) => setFtp(e.target.value)}
              className="w-full h-9 px-3 text-body bg-surface-raised border border-border rounded-md
                         text-text-primary placeholder:text-text-disabled
                         focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent"
            />
          </div>
          <div>
            <label className="block text-label text-text-secondary mb-1" htmlFor="profile-hrmax">
              Max HR <span className="text-text-disabled">(bpm)</span>
            </label>
            <input
              id="profile-hrmax"
              type="number"
              inputMode="numeric"
              min={100}
              max={260}
              placeholder="e.g. 188"
              value={hrMax}
              onChange={(e) => setHrMax(e.target.value)}
              className="w-full h-9 px-3 text-body bg-surface-raised border border-border rounded-md
                         text-text-primary placeholder:text-text-disabled
                         focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent"
            />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="secondary" size="sm" loading={saving} onClick={save}>
            {saved ? '✓ Saved' : 'Save profile'}
          </Button>
          {error && <p className="text-body-sm text-error">{error}</p>}
        </div>
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
          Manage your account.
        </p>
      </div>

      <div className="space-y-4 max-w-xl">
        <ProfileCard />
        <TrainingProfileCard />
        <DangerZoneCard />
      </div>
    </div>
  )
}
