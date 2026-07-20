'use client'

import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, Badge } from '@/components/ui'
import { formatCents } from '@/lib/utils'
import {
  useAdminAlerts,
  useAdminGovernorState,
  useAdminMetricsOverview,
  useAdminRevenue,
} from '@/hooks/use-admin'

const LEVEL_LABELS = ['Normal', 'Soft throttle', 'Deferred', 'Admission freeze', 'Paused']

const SEVERITY_ICON = {
  ok: CheckCircle2,
  info: Info,
  warning: AlertTriangle,
  critical: XCircle,
} as const

const SEVERITY_CLASS = {
  ok: 'text-success',
  info: 'text-info',
  warning: 'text-warning',
  critical: 'text-error',
} as const

function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="p-4 rounded-lg border border-border bg-surface-raised">
      <p className="text-caption text-text-secondary">{label}</p>
      <p className="text-heading-lg text-text-primary font-bold mt-1">{value}</p>
      {hint && <p className="text-caption text-text-disabled mt-1">{hint}</p>}
    </div>
  )
}

export function OverviewTab() {
  const { data: overview, isLoading: loadingOverview } = useAdminMetricsOverview()
  const { data: revenue, isLoading: loadingRevenue } = useAdminRevenue()
  const { data: gstate, isLoading: loadingGstate } = useAdminGovernorState()
  const { data: alerts, isLoading: loadingAlerts } = useAdminAlerts()

  const isLoading = loadingOverview || loadingRevenue || loadingGstate

  if (isLoading || !overview || !revenue || !gstate) {
    return (
      <div className="flex items-center gap-2 text-text-secondary text-body-sm py-8">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading economics…
      </div>
    )
  }

  const cost = overview.monthly_cost_cents
  const rev = revenue.monthly_revenue_cents
  const coveragePct = rev > 0 ? Math.round((cost / rev) * 100) : cost === 0 ? 0 : 999
  const slotsUsedPct = gstate.strava_total_slots
    ? Math.round(((gstate.strava_total_slots - gstate.strava_free_capacity_slots + gstate.strava_free_slots_used) / gstate.strava_total_slots) * 100)
    : 0

  return (
    <div className="space-y-6">
      {overview.self_hosted && (
        <div className="text-body-sm text-text-secondary px-4 py-3 rounded-md bg-info-light">
          Self-hosted instance — economics, degradation and admission control don&rsquo;t apply here.
        </div>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatTile
          label="Monthly cost"
          value={formatCents(cost)}
          hint={`${overview.strava.active_apps} active Strava app${overview.strava.active_apps === 1 ? '' : 's'}`}
        />
        <StatTile
          label="Monthly revenue (est.)"
          value={formatCents(rev)}
          hint={`${revenue.active_paid_subscriptions} paid subscription${revenue.active_paid_subscriptions === 1 ? '' : 's'}`}
        />
        <StatTile
          label="Coverage"
          value={rev > 0 ? `${coveragePct}%` : cost === 0 ? '—' : '∞'}
          hint={`target ≤ ${overview.coverage_target_pct}%`}
        />
        <StatTile
          label="Degradation level"
          value={LEVEL_LABELS[gstate.free_tier_level] ?? String(gstate.free_tier_level)}
          hint={gstate.strava_admission_open ? 'Strava admission open' : 'Strava admission closed'}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Strava slot occupancy</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between text-body-sm">
            <span className="text-text-secondary">
              {gstate.strava_total_slots - gstate.strava_free_capacity_slots + gstate.strava_free_slots_used} / {gstate.strava_total_slots} slots used
            </span>
            <span className="text-text-secondary">
              {gstate.strava_free_slots_used} / {gstate.strava_free_capacity_slots} free-tier slots used
            </span>
          </div>
          <div className="h-2 rounded-full bg-border overflow-hidden">
            <div
              className={slotsUsedPct > 80 ? 'h-full bg-warning' : 'h-full bg-primary'}
              style={{ width: `${Math.min(slotsUsedPct, 100)}%` }}
            />
          </div>
          <p className="text-caption text-text-disabled">
            {gstate.strava_reserved_paid_slots} slots reserved for paid tiers ({overview.paid_reservation_pct}%)
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Alerts</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {loadingAlerts ? (
            <div className="flex items-center gap-2 text-text-secondary text-body-sm">
              <Loader2 className="w-4 h-4 animate-spin" /> Loading…
            </div>
          ) : (
            (alerts ?? []).map((a, i) => {
              const Icon = SEVERITY_ICON[a.severity]
              return (
                <div key={i} className="flex items-start gap-2 text-body-sm">
                  <Icon className={`w-4 h-4 flex-shrink-0 mt-0.5 ${SEVERITY_CLASS[a.severity]}`} />
                  <span className="text-text-primary">{a.message}</span>
                  <Badge variant={a.severity === 'critical' ? 'error' : a.severity === 'warning' ? 'paused' : 'neutral'}>
                    {a.severity}
                  </Badge>
                </div>
              )
            })
          )}
        </CardContent>
      </Card>
    </div>
  )
}
