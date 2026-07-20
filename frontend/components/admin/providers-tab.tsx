'use client'

import { useState } from 'react'
import { Loader2, Pencil, Plus, X } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, Button, Badge, Input, Textarea } from '@/components/ui'
import { formatCents } from '@/lib/utils'
import {
  useAdminProviders,
  useAdminProvidersOverview,
  useAdminStravaApps,
  useCreateAdminStravaApp,
  useUpdateAdminProvider,
  useUpdateAdminStravaApp,
} from '@/hooks/use-admin'
import type { AdminProviderOverviewRow, AdminProviderPolicy, AdminStravaApp } from '@/types/api'

// ── Cross-provider overview table ───────────────────────────────────────────────

function limitsSummary(row: AdminProviderOverviewRow): string {
  if (row.overall_limit_15min != null) {
    return `${row.read_limit_15min ?? '—'}/15min·${row.read_limit_daily ?? '—'}/day read, ${row.overall_limit_15min}/15min·${row.overall_limit_daily}/day overall`
  }
  if (row.window_seconds != null && row.window_limit != null) {
    return `${row.window_limit} req / ${row.window_seconds}s per account`
  }
  return 'no configured limit'
}

function OverviewTable() {
  const { data: rows, isLoading } = useAdminProvidersOverview()

  if (isLoading || !rows) {
    return (
      <div className="flex items-center gap-2 text-text-secondary text-body-sm py-4">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading…
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-body-sm">
        <thead>
          <tr className="text-left text-caption text-text-secondary border-b border-border">
            <th className="pb-2 pr-4">Provider</th>
            <th className="pb-2 pr-4">Tier</th>
            <th className="pb-2 pr-4">Users</th>
            <th className="pb-2 pr-4">Cost</th>
            <th className="pb-2 pr-4">Cadence</th>
            <th className="pb-2">Limits</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.platform} className="border-b border-border last:border-0 align-top">
              <td className="py-2 pr-4">
                <span className="text-text-primary font-medium capitalize">
                  {row.platform.replace('_', '.')}
                </span>
                {!row.enabled && (
                  <Badge variant="paused" className="ml-2">
                    disabled
                  </Badge>
                )}
              </td>
              <td className="py-2 pr-4 text-text-secondary max-w-[220px]">
                {row.tier_label ?? '—'}
              </td>
              <td className="py-2 pr-4 text-text-secondary">
                {row.connected_users}
                {row.capacity_note && (
                  <p className="text-caption text-text-disabled">{row.capacity_note}</p>
                )}
              </td>
              <td className="py-2 pr-4 text-text-secondary">
                {row.monthly_cost_cents > 0 ? `${formatCents(row.monthly_cost_cents)}/mo` : 'free'}
              </td>
              <td className="py-2 pr-4 text-text-secondary">
                {row.refresh_strategy === 'webhook'
                  ? 'webhook'
                  : row.default_poll_min
                    ? `every ${row.default_poll_min}min`
                    : '—'}
              </td>
              <td className="py-2 text-text-secondary">{limitsSummary(row)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Full provider edit form ──────────────────────────────────────────────────────

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div>
      <label className="block text-label text-text-secondary mb-1">{label}</label>
      <Input type="number" value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}

function ProviderRow({ policy }: { policy: AdminProviderPolicy }) {
  const [editing, setEditing] = useState(false)
  const { mutate: update, isPending, error } = useUpdateAdminProvider()

  const [form, setForm] = useState({
    enabled: policy.enabled,
    tier_label: policy.tier_label ?? '',
    notes: policy.notes ?? '',
    default_poll_min: String(policy.default_poll_min ?? ''),
    min_poll_min: String(policy.min_poll_min ?? ''),
    window_seconds: String(policy.window_seconds ?? ''),
    window_limit: String(policy.window_limit ?? ''),
    daily_limit: String(policy.daily_limit ?? ''),
    read_limit_15min: String(policy.read_limit_15min ?? ''),
    read_limit_daily: String(policy.read_limit_daily ?? ''),
    overall_limit_15min: String(policy.overall_limit_15min ?? ''),
    overall_limit_daily: String(policy.overall_limit_daily ?? ''),
    monthly_cost_dollars: (policy.monthly_cost_cents / 100).toFixed(2),
    initial_backfill_limit: String(policy.initial_backfill_limit ?? ''),
    page_size: String(policy.page_size ?? ''),
    refresh_strategy: policy.refresh_strategy,
    headroom_pct: String(policy.headroom_pct),
    free_reserve_pct: String(policy.free_reserve_pct),
  })

  function num(v: string): number | null {
    return v.trim() === '' ? null : parseInt(v, 10)
  }

  function save() {
    update(
      {
        platform: policy.platform,
        enabled: form.enabled,
        tier_label: form.tier_label || null,
        notes: form.notes || null,
        default_poll_min: num(form.default_poll_min),
        min_poll_min: num(form.min_poll_min),
        window_seconds: num(form.window_seconds),
        window_limit: num(form.window_limit),
        daily_limit: num(form.daily_limit),
        read_limit_15min: num(form.read_limit_15min),
        read_limit_daily: num(form.read_limit_daily),
        overall_limit_15min: num(form.overall_limit_15min),
        overall_limit_daily: num(form.overall_limit_daily),
        monthly_cost_cents: Math.round(parseFloat(form.monthly_cost_dollars || '0') * 100),
        initial_backfill_limit: num(form.initial_backfill_limit),
        page_size: num(form.page_size),
        refresh_strategy: form.refresh_strategy,
        headroom_pct: parseInt(form.headroom_pct, 10),
        free_reserve_pct: parseInt(form.free_reserve_pct, 10),
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
          {policy.tier_label && (
            <p className="text-caption text-text-secondary mt-0.5">{policy.tier_label}</p>
          )}
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
        <div className="mt-4 space-y-5">
          <div className="flex items-center justify-between">
            <label className="text-body-sm text-text-primary">Enabled</label>
            <button
              type="button"
              role="switch"
              aria-checked={form.enabled}
              onClick={() => setForm((f) => ({ ...f, enabled: !f.enabled }))}
              className={`relative inline-flex h-6 w-11 flex-shrink-0 rounded-full border-2 border-transparent
                transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2
                ${form.enabled ? 'bg-primary' : 'bg-border-strong'}`}
            >
              <span
                className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow
                  transition duration-200 ${form.enabled ? 'translate-x-5' : 'translate-x-0'}`}
              />
            </button>
          </div>

          <div>
            <label className="block text-label text-text-secondary mb-1">Tier label</label>
            <Input
              value={form.tier_label}
              onChange={(e) => setForm((f) => ({ ...f, tier_label: e.target.value }))}
              placeholder="e.g. Standard, self-upgraded (10 athletes)"
            />
          </div>

          <div>
            <label className="block text-label text-text-secondary mb-1">Notes</label>
            <Textarea
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              rows={2}
            />
          </div>

          <div>
            <p className="text-label text-text-secondary mb-2">Poll cadence</p>
            <div className="grid grid-cols-2 gap-3 max-w-sm">
              <NumberField
                label="Default (min)"
                value={form.default_poll_min}
                onChange={(v) => setForm((f) => ({ ...f, default_poll_min: v }))}
              />
              <NumberField
                label="Minimum (min)"
                value={form.min_poll_min}
                onChange={(v) => setForm((f) => ({ ...f, min_poll_min: v }))}
              />
            </div>
          </div>

          <div>
            <p className="text-label text-text-secondary mb-2">
              Rate limits — window (destination platforms)
            </p>
            <div className="grid grid-cols-3 gap-3 max-w-lg">
              <NumberField
                label="Window (sec)"
                value={form.window_seconds}
                onChange={(v) => setForm((f) => ({ ...f, window_seconds: v }))}
              />
              <NumberField
                label="Req per window"
                value={form.window_limit}
                onChange={(v) => setForm((f) => ({ ...f, window_limit: v }))}
              />
              <NumberField
                label="Daily cap"
                value={form.daily_limit}
                onChange={(v) => setForm((f) => ({ ...f, daily_limit: v }))}
              />
            </div>
          </div>

          <div>
            <p className="text-label text-text-secondary mb-2">
              Rate limits — read / overall (Strava-style, per-app defaults)
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 max-w-xl">
              <NumberField
                label="Read /15min"
                value={form.read_limit_15min}
                onChange={(v) => setForm((f) => ({ ...f, read_limit_15min: v }))}
              />
              <NumberField
                label="Read /day"
                value={form.read_limit_daily}
                onChange={(v) => setForm((f) => ({ ...f, read_limit_daily: v }))}
              />
              <NumberField
                label="Overall /15min"
                value={form.overall_limit_15min}
                onChange={(v) => setForm((f) => ({ ...f, overall_limit_15min: v }))}
              />
              <NumberField
                label="Overall /day"
                value={form.overall_limit_daily}
                onChange={(v) => setForm((f) => ({ ...f, overall_limit_daily: v }))}
              />
            </div>
          </div>

          <div>
            <p className="text-label text-text-secondary mb-2">Cost &amp; import</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 max-w-xl">
              <div>
                <label className="block text-label text-text-secondary mb-1">Cost ($/mo)</label>
                <Input
                  type="number"
                  step="0.01"
                  value={form.monthly_cost_dollars}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, monthly_cost_dollars: e.target.value }))
                  }
                />
              </div>
              <NumberField
                label="Initial backfill"
                value={form.initial_backfill_limit}
                onChange={(v) => setForm((f) => ({ ...f, initial_backfill_limit: v }))}
              />
              <NumberField
                label="Page size"
                value={form.page_size}
                onChange={(v) => setForm((f) => ({ ...f, page_size: v }))}
              />
              <div>
                <label className="block text-label text-text-secondary mb-1">Refresh</label>
                <select
                  value={form.refresh_strategy}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      refresh_strategy: e.target.value as AdminProviderPolicy['refresh_strategy'],
                    }))
                  }
                  className="w-full h-9 px-2 text-body-sm bg-surface-raised border border-border rounded-md
                             text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
                >
                  <option value="webhook">webhook</option>
                  <option value="poll">poll</option>
                  <option value="none">none</option>
                </select>
              </div>
            </div>
          </div>

          <div>
            <p className="text-label text-text-secondary mb-2">
              Fairness (economic governor inputs)
            </p>
            <div className="grid grid-cols-2 gap-3 max-w-sm">
              <NumberField
                label="Headroom %"
                value={form.headroom_pct}
                onChange={(v) => setForm((f) => ({ ...f, headroom_pct: v }))}
              />
              <NumberField
                label="Free reserve %"
                value={form.free_reserve_pct}
                onChange={(v) => setForm((f) => ({ ...f, free_reserve_pct: v }))}
              />
            </div>
          </div>

          {error && <p className="text-body-sm text-error">{(error as Error).message}</p>}

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
          {app.connected_athletes !== null && (
            <Badge variant={app.connected_athletes >= app.athlete_cap ? 'error' : 'neutral'}>
              {app.connected_athletes}/{app.athlete_cap} connected
            </Badge>
          )}
        </div>
        <p className="text-caption text-text-disabled mt-0.5">
          {app.athlete_cap} slot cap (manual — Strava has no API for this) ·{' '}
          {formatCents(app.monthly_cost_cents)}/mo · read {app.read_limit_15min}/15min·
          {app.read_limit_daily}/day · overall {app.overall_limit_15min}/15min·
          {app.overall_limit_daily}/day
        </p>
        <p className="text-caption text-text-disabled">
          Limits above sync automatically from Strava&rsquo;s response headers.
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
          <CardTitle>Overview by provider</CardTitle>
        </CardHeader>
        <CardContent>
          <OverviewTable />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Manage providers</CardTitle>
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
