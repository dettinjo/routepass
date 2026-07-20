'use client'

import { useState } from 'react'
import { Loader2, Pencil, Plus, X } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, Button, Badge, Input } from '@/components/ui'
import { formatCents } from '@/lib/utils'
import {
  useAdminProviders,
  useAdminStravaApps,
  useCreateAdminStravaApp,
  useUpdateAdminProvider,
  useUpdateAdminStravaApp,
} from '@/hooks/use-admin'
import type { AdminProviderPolicy, AdminStravaApp } from '@/types/api'

// ── Provider row ──────────────────────────────────────────────────────────────

function ProviderRow({ policy }: { policy: AdminProviderPolicy }) {
  const [editing, setEditing] = useState(false)
  const [defaultPoll, setDefaultPoll] = useState(String(policy.default_poll_min ?? ''))
  const [minPoll, setMinPoll] = useState(String(policy.min_poll_min ?? ''))
  const { mutate: update, isPending } = useUpdateAdminProvider()

  function save() {
    update(
      {
        platform: policy.platform,
        default_poll_min: defaultPoll ? parseInt(defaultPoll, 10) : null,
        min_poll_min: minPoll ? parseInt(minPoll, 10) : null,
      },
      { onSuccess: () => setEditing(false) },
    )
  }

  return (
    <div className="py-3 border-b border-border last:border-0">
      <div className="flex items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-body font-medium text-text-primary capitalize">
              {policy.platform.replace('_', '.')}
            </span>
            <Badge variant="neutral">{policy.role}</Badge>
            {policy.supports_webhooks && <Badge variant="connected">webhook</Badge>}
            {!policy.enabled && <Badge variant="paused">disabled</Badge>}
          </div>
          <p className="text-caption text-text-disabled mt-0.5">
            poll {policy.default_poll_min ?? '—'}min (min {policy.min_poll_min ?? '—'}min) ·{' '}
            {policy.monthly_cost_cents > 0 ? formatCents(policy.monthly_cost_cents) + '/mo' : 'free'}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => setEditing((v) => !v)}>
          {editing ? <X className="w-4 h-4" /> : <Pencil className="w-4 h-4" />}
        </Button>
      </div>

      {editing && (
        <div className="mt-3 flex items-end gap-3">
          <div>
            <label className="block text-label text-text-secondary mb-1">Default poll (min)</label>
            <Input
              type="number"
              value={defaultPoll}
              onChange={(e) => setDefaultPoll(e.target.value)}
              className="w-28"
            />
          </div>
          <div>
            <label className="block text-label text-text-secondary mb-1">Min poll (min)</label>
            <Input
              type="number"
              value={minPoll}
              onChange={(e) => setMinPoll(e.target.value)}
              className="w-28"
            />
          </div>
          <Button variant="primary" size="sm" loading={isPending} onClick={save}>
            Save
          </Button>
        </div>
      )}
    </div>
  )
}

// ── Strava app row ────────────────────────────────────────────────────────────

function StravaAppRow({ app }: { app: AdminStravaApp }) {
  const { mutate: update, isPending } = useUpdateAdminStravaApp()

  return (
    <div className="flex items-center gap-4 py-3 border-b border-border last:border-0">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-body font-medium text-text-primary">{app.display_name}</span>
          <Badge variant={app.is_active ? 'connected' : 'neutral'}>
            {app.is_active ? 'active' : 'inactive'}
          </Badge>
        </div>
        <p className="text-caption text-text-disabled mt-0.5">
          {app.athlete_cap} slots · {formatCents(app.monthly_cost_cents)}/mo · read{' '}
          {app.read_limit_15min}/15min·{app.read_limit_daily}/day · overall {app.overall_limit_15min}
          /15min·{app.overall_limit_daily}/day
        </p>
      </div>
      <Button
        variant="secondary"
        size="sm"
        loading={isPending}
        onClick={() => update({ id: app.id, is_active: !app.is_active })}
      >
        {app.is_active ? 'Deactivate' : 'Activate'}
      </Button>
    </div>
  )
}

function AddStravaAppForm({ onClose }: { onClose: () => void }) {
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [athleteCap, setAthleteCap] = useState('10')
  const [monthlyCost, setMonthlyCost] = useState('11.99')
  const { mutate: create, isPending, error } = useCreateAdminStravaApp()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    create(
      {
        client_id: clientId,
        client_secret: clientSecret,
        display_name: displayName,
        athlete_cap: parseInt(athleteCap, 10),
        monthly_cost_cents: Math.round(parseFloat(monthlyCost) * 100),
      },
      { onSuccess: onClose },
    )
  }

  return (
    <form onSubmit={handleSubmit} className="mt-4 pt-4 border-t border-border space-y-3">
      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-label text-text-secondary mb-1">Display name</label>
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
        </div>
        <div>
          <label className="block text-label text-text-secondary mb-1">Client ID</label>
          <Input value={clientId} onChange={(e) => setClientId(e.target.value)} required />
        </div>
        <div>
          <label className="block text-label text-text-secondary mb-1">Client secret</label>
          <Input
            type="password"
            value={clientSecret}
            onChange={(e) => setClientSecret(e.target.value)}
            required
          />
        </div>
        <div>
          <label className="block text-label text-text-secondary mb-1">Athlete cap</label>
          <Input type="number" value={athleteCap} onChange={(e) => setAthleteCap(e.target.value)} />
        </div>
        <div>
          <label className="block text-label text-text-secondary mb-1">Monthly cost ($)</label>
          <Input
            type="number"
            step="0.01"
            value={monthlyCost}
            onChange={(e) => setMonthlyCost(e.target.value)}
          />
        </div>
      </div>
      {error && <p className="text-body-sm text-error">{(error as Error).message}</p>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" size="sm" loading={isPending}>
          Add app
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

// ── Tab ───────────────────────────────────────────────────────────────────────

export function ProvidersTab() {
  const { data: providers, isLoading: loadingProviders } = useAdminProviders()
  const { data: apps, isLoading: loadingApps } = useAdminStravaApps()
  const [showAddApp, setShowAddApp] = useState(false)

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Providers</CardTitle>
        </CardHeader>
        <CardContent>
          {loadingProviders ? (
            <div className="flex items-center gap-2 text-text-secondary text-body-sm py-4">
              <Loader2 className="w-4 h-4 animate-spin" /> Loading…
            </div>
          ) : (
            (providers ?? []).map((p) => <ProviderRow key={p.platform} policy={p} />)
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex items-center justify-between">
          <CardTitle>Strava app pool</CardTitle>
          <Button variant="secondary" size="sm" onClick={() => setShowAddApp((v) => !v)}>
            {showAddApp ? <X className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
            {showAddApp ? 'Cancel' : 'Add app'}
          </Button>
        </CardHeader>
        <CardContent>
          {loadingApps ? (
            <div className="flex items-center gap-2 text-text-secondary text-body-sm py-4">
              <Loader2 className="w-4 h-4 animate-spin" /> Loading…
            </div>
          ) : (apps ?? []).length === 0 ? (
            <p className="text-body-sm text-text-secondary">No Strava apps configured.</p>
          ) : (
            (apps ?? []).map((a) => <StravaAppRow key={a.id} app={a} />)
          )}
          {showAddApp && <AddStravaAppForm onClose={() => setShowAddApp(false)} />}
        </CardContent>
      </Card>
    </div>
  )
}
