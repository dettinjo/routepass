'use client'

import { RefreshCw, Zap, Activity, AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge, StatusDot } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { SportIcon } from '@/components/sport-icon'
import { useSyncStatus, useTriggerSync } from '@/hooks/use-sync-status'
import { useConnections } from '@/hooks/use-connections'
import { useActivities } from '@/hooks/use-activities'
import { formatRelative, formatDistance, formatDuration, sportLabel } from '@/lib/utils'

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-surface-raised border border-border rounded-lg px-5 py-4">
      <p className="text-label text-text-secondary uppercase tracking-wide">{label}</p>
      <p className="text-heading-lg text-text-primary mt-1">{value}</p>
      {sub && <p className="text-caption text-text-disabled mt-0.5">{sub}</p>}
    </div>
  )
}

export default function DashboardPage() {
  const { data: sync, isLoading: syncLoading } = useSyncStatus()
  const { data: connections } = useConnections()
  const { data: activities } = useActivities({ limit: 5 })
  const { mutate: triggerSync, isPending: syncing } = useTriggerSync()

  const connectedCount = (connections ?? []).filter((c) => c.status === 'active').length
  const hasError = !!sync?.last_error

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-heading-xl text-text-primary">Dashboard</h1>
          <p className="text-body text-text-secondary mt-1">
            Your sync status and recent activity at a glance.
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => triggerSync()}
          loading={syncing}
        >
          <RefreshCw className="w-4 h-4" />
          Sync now
        </Button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Connections"
          value={connectedCount}
          sub={connectedCount === 1 ? '1 platform active' : `${connectedCount} platforms active`}
        />
        <StatCard
          label="Total synced"
          value={sync?.total_synced_count ?? '—'}
          sub="all time"
        />
        <StatCard
          label="Last sync"
          value={
            sync?.last_successful_sync_at
              ? formatRelative(new Date(sync.last_successful_sync_at))
              : '—'
          }
        />
        <StatCard
          label="Status"
          value={hasError ? 'Error' : sync?.komoot_connected && sync?.strava_connected ? 'Active' : 'Incomplete'}
          sub={hasError ? 'See error below' : undefined}
        />
      </div>

      {/* Sync status card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-primary" />
            Sync pipeline
          </CardTitle>
        </CardHeader>
        <CardContent>
          {syncLoading ? (
            <div className="flex items-center gap-2 text-text-secondary text-body-sm py-4">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading…
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between py-2 border-b border-border last:border-0">
                <div className="flex items-center gap-3">
                  <StatusDot status={sync?.komoot_connected ? 'active' : 'inactive'} />
                  <span className="text-body text-text-primary">Komoot</span>
                </div>
                <Badge variant={sync?.komoot_connected ? 'connected' : 'neutral'}>
                  {sync?.komoot_connected ? 'Connected' : 'Not connected'}
                </Badge>
              </div>
              <div className="flex items-center justify-between py-2 border-b border-border last:border-0">
                <div className="flex items-center gap-3">
                  <StatusDot status={sync?.strava_connected ? 'active' : 'inactive'} />
                  <span className="text-body text-text-primary">Strava</span>
                </div>
                <Badge variant={sync?.strava_connected ? 'connected' : 'neutral'}>
                  {sync?.strava_connected ? 'Connected' : 'Not connected'}
                </Badge>
              </div>

              {hasError && (
                <div className="flex items-start gap-3 mt-2 px-4 py-3 bg-error-light rounded-md">
                  <AlertTriangle className="w-4 h-4 text-error flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-body-sm text-error font-medium">Last sync failed</p>
                    <p className="text-caption text-error mt-0.5">{sync.last_error}</p>
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recent activities */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-primary" />
            Recent activity
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {!activities?.data?.length ? (
            <div className="px-6 py-8 text-center text-text-secondary text-body-sm">
              No synced activities yet. Connect Komoot and Strava to get started.
            </div>
          ) : (
            <div className="divide-y divide-border">
              {activities.data.slice(0, 5).map((act) => (
                <div key={act.id} className="flex items-center gap-4 px-6 py-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-body text-text-primary truncate">
                      {act.activity_name ?? 'Untitled activity'}
                    </p>
                    <p className="flex items-center gap-1.5 text-caption text-text-secondary">
                      <SportIcon sportType={act.sport_type ?? ''} size={14} className="opacity-70" />
                      <span>
                        {sportLabel(act.sport_type ?? '')}
                        {act.distance_m ? ` · ${formatDistance(act.distance_m)}` : ''}
                        {act.duration_seconds ? ` · ${formatDuration(act.duration_seconds)}` : ''}
                      </span>
                    </p>
                  </div>
                  <div className="flex-shrink-0 text-right">
                    <Badge variant={act.sync_status === 'completed' ? 'connected' : act.sync_status === 'failed' ? 'error' : 'pending'}>
                      {act.sync_status === 'completed' ? (
                        <CheckCircle2 className="w-3 h-3" />
                      ) : null}
                      {act.sync_status}
                    </Badge>
                    <p className="text-caption text-text-disabled mt-1">
                      {formatRelative(new Date(act.synced_at))}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
