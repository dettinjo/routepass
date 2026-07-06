'use client'

import { useState } from 'react'
import { CheckCircle2, AlertCircle, Clock, ExternalLink, Loader2, X } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { BrandBox } from '@/components/brand-box'
import { useConnections, useCreateConnection, useDeleteConnection } from '@/hooks/use-connections'
import { useAuthStore } from '@/store/auth'
import { formatRelative } from '@/lib/utils'
import type { PlatformKey } from '@/types/api'

// ── Platform definitions ───────────────────────────────────────────────────────

type ConnectType = 'oauth' | 'credentials' | 'api_key' | 'coming_soon'

interface PlatformDef {
  key: PlatformKey
  label: string
  description: string
  type: ConnectType
  fields?: { key: string; label: string; type?: string; placeholder?: string; hint?: string }[]
}

const PLATFORMS: PlatformDef[] = [
  {
    key: 'komoot',
    label: 'Komoot',
    description: 'Fetch tours from Komoot and sync them to your destinations.',
    type: 'credentials',
    fields: [
      { key: 'email', label: 'Komoot email', type: 'email', placeholder: 'you@example.com' },
      { key: 'password', label: 'Komoot password', type: 'password', placeholder: '••••••••' },
    ],
  },
  {
    key: 'strava',
    label: 'Strava',
    description: 'Receive synced activities from Komoot as Strava workouts.',
    type: 'oauth',
  },
  {
    key: 'intervals_icu',
    label: 'Intervals.icu',
    description: 'Push activity data to Intervals.icu for training analytics.',
    type: 'api_key',
    fields: [
      { key: 'api_key', label: 'API key', placeholder: 'i_XXXXXXXX' },
      { key: 'athlete_id', label: 'Athlete ID', placeholder: 'iXXXXXXXX' },
    ],
  },
  {
    key: 'runalyze',
    label: 'Runalyze',
    description: 'Upload GPX files directly to Runalyze.',
    type: 'api_key',
    fields: [{ key: 'token', label: 'Personal access token', placeholder: 'rp_…' }],
  },
  {
    key: 'garmin',
    label: 'Garmin Connect',
    description: 'Sync activities from Garmin devices.',
    type: 'coming_soon',
  },
  {
    key: 'polar',
    label: 'Polar Flow',
    description: 'Pull workouts from Polar training platform.',
    type: 'coming_soon',
  },
  {
    key: 'wahoo',
    label: 'Wahoo',
    description: 'Ingest rides and workouts from Wahoo devices.',
    type: 'coming_soon',
  },
  {
    key: 'trainingpeaks',
    label: 'TrainingPeaks',
    description: 'Sync structured training data with TrainingPeaks.',
    type: 'coming_soon',
  },
]

// ── Inline connect form ────────────────────────────────────────────────────────

function ConnectForm({
  platform,
  onClose,
}: {
  platform: PlatformDef
  onClose: () => void
}) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [oauthPending, setOauthPending] = useState(false)
  const [oauthError, setOauthError] = useState<string | null>(null)
  const { mutate: create, isPending, error } = useCreateConnection()
  const token = useAuthStore((s) => s.token)

  if (platform.type === 'oauth') {
    const handleStravaAuth = async () => {
      setOauthPending(true)
      setOauthError(null)
      try {
        const res = await fetch('/api/v1/auth/strava/login', {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!res.ok) throw new Error('Failed to get Strava auth URL')
        const { url } = await res.json()
        window.location.href = url
      } catch (err) {
        setOauthError(err instanceof Error ? err.message : 'Could not start Strava authorisation')
        setOauthPending(false)
      }
    }

    return (
      <div className="mt-4 pt-4 border-t border-border space-y-2">
        <div className="flex items-center gap-3">
          <Button variant="primary" size="sm" loading={oauthPending} onClick={handleStravaAuth}>
            <ExternalLink className="w-3.5 h-3.5" />
            Authorise with Strava
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
        </div>
        {oauthError && <p className="text-body-sm text-error">{oauthError}</p>}
      </div>
    )
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    create(
      {
        platform: platform.key,
        display_name: values.email || values.athlete_id || platform.label,
        credentials: values,
      },
      { onSuccess: onClose },
    )
  }

  return (
    <form onSubmit={handleSubmit} className="mt-4 pt-4 border-t border-border space-y-3">
      {platform.fields?.map((f) => (
        <div key={f.key}>
          <label className="block text-label text-text-secondary mb-1">{f.label}</label>
          <input
            type={f.type ?? 'text'}
            placeholder={f.placeholder}
            value={values[f.key] ?? ''}
            onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
            required={f.key !== 'user_id'}
            className="w-full h-9 px-3 text-body bg-surface-raised border border-border rounded-md
                       text-text-primary placeholder:text-text-disabled
                       focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent"
          />
          {f.hint && (
            <p className="text-caption text-text-disabled mt-1">{f.hint}</p>
          )}
        </div>
      ))}
      {error && (
        <p className="text-body-sm text-error">{(error as Error).message}</p>
      )}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" size="sm" loading={isPending}>
          Connect
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

// ── Platform card ──────────────────────────────────────────────────────────────

function PlatformCard({
  platform,
  connection,
}: {
  platform: PlatformDef
  connection?: { id: string; display_name: string; status: string; last_synced_at: string | null }
}) {
  const [expanded, setExpanded] = useState(false)
  const { mutate: disconnect, isPending: disconnecting } = useDeleteConnection()
  const isConnected = !!connection
  const isComingSoon = platform.type === 'coming_soon'

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-start gap-4">
          {/* Brand logo — official SVG for platforms that have one */}
          <BrandBox brand={platform.key} size={40} className="flex-shrink-0" variant={isComingSoon ? 'inactive' : 'regular'} />

          {/* Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-heading-sm text-text-primary">{platform.label}</span>
              {isConnected && connection.status === 'active' && (
                <Badge variant="connected">
                  <CheckCircle2 className="w-3 h-3" />
                  Connected
                </Badge>
              )}
              {isConnected && connection.status === 'error' && (
                <Badge variant="error">
                  <AlertCircle className="w-3 h-3" />
                  Error
                </Badge>
              )}
              {isComingSoon && (
                <Badge variant="neutral">Coming soon</Badge>
              )}
            </div>
            <p className="text-body-sm text-text-secondary mt-0.5">{platform.description}</p>
            {isConnected && connection.display_name && (
              <p className="text-caption text-text-disabled mt-1 truncate">{connection.display_name}</p>
            )}
            {isConnected && connection.last_synced_at && (
              <p className="text-caption text-text-disabled flex items-center gap-1 mt-0.5">
                <Clock className="w-3 h-3" />
                Last synced {formatRelative(new Date(connection.last_synced_at))}
              </p>
            )}
          </div>

          {/* Action */}
          <div className="flex-shrink-0">
            {isConnected ? (
              <Button
                variant="secondary"
                size="sm"
                loading={disconnecting}
                onClick={() => disconnect(connection.id)}
              >
                Disconnect
              </Button>
            ) : !isComingSoon ? (
              <Button
                variant={expanded ? 'ghost' : 'secondary'}
                size="sm"
                onClick={() => setExpanded((v) => !v)}
              >
                {expanded ? <X className="w-4 h-4" /> : 'Connect'}
              </Button>
            ) : null}
          </div>
        </div>

        {expanded && !isConnected && (
          <ConnectForm platform={platform} onClose={() => setExpanded(false)} />
        )}
      </CardContent>
    </Card>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function ConnectionsPage() {
  const { data: connections, isLoading } = useConnections()

  const byPlatform = Object.fromEntries(
    (connections ?? []).map((c) => [c.platform, c]),
  )

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-heading-xl text-text-primary">Connections</h1>
        <p className="text-body text-text-secondary mt-1">
          Connect RoutePass to your training platforms.
        </p>
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 text-text-secondary text-body-sm py-8">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading connections…
        </div>
      ) : (
        <div className="grid gap-4">
          {PLATFORMS.map((platform) => (
            <PlatformCard
              key={platform.key}
              platform={platform}
              connection={byPlatform[platform.key]}
            />
          ))}
        </div>
      )}
    </div>
  )
}
