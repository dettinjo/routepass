'use client'

import { AlertTriangle, Loader2 } from 'lucide-react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Badge } from '@/components/ui/badge'
import { formatDistance, formatDuration, isPaidTier, sportLabel } from '@/lib/utils'
import { useActivityRecords, useTrainingLoad } from '@/hooks/use-activities'
import { useAuthStore } from '@/store/auth'
import type { RecordEntry, TsbStatus } from '@/types/api'

const TOOLTIP_STYLE = {
  background: 'var(--color-surface-raised)',
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  fontSize: 12,
} as const

const STATUS_LABEL: Record<TsbStatus, string> = {
  very_fresh: 'Very fresh',
  fresh: 'Fresh',
  neutral: 'Neutral',
  fatigued: 'Fatigued',
  very_fatigued: 'Very fatigued',
}
// Reuses existing semantic badge variants — no new status colors invented.
const STATUS_BADGE: Record<TsbStatus, 'connected' | 'neutral' | 'paused' | 'error'> = {
  very_fresh: 'connected',
  fresh: 'connected',
  neutral: 'neutral',
  fatigued: 'paused',
  very_fatigued: 'error',
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-surface-raised px-3 py-2.5 flex flex-col items-center gap-1 text-center">
      <p className="text-heading-sm text-text-primary font-semibold tabular-nums leading-none">{value}</p>
      <p className="text-[9px] font-medium text-text-disabled uppercase tracking-wider leading-none">{label}</p>
      {sub && <p className="text-[10px] text-text-disabled leading-none">{sub}</p>}
    </div>
  )
}

function RecordRow({ label, entry, format }: { label: string; entry: RecordEntry | null; format: (v: number) => string }) {
  if (!entry) return null
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 border-b border-border last:border-0">
      <span className="text-caption text-text-secondary">{label}</span>
      <div className="text-right">
        <p className="text-body-sm text-text-primary font-medium tabular-nums">{format(entry.value)}</p>
        <p className="text-[10px] text-text-disabled truncate max-w-[160px]">{entry.name ?? 'Untitled'}</p>
      </div>
    </div>
  )
}

function UpsellBanner() {
  return (
    <div className="rounded-xl border border-border bg-surface overflow-hidden">
      <div className="flex items-center justify-between gap-4 px-4 py-3">
        <span className="text-body-sm font-medium text-text-primary">Training load & records</span>
        <Badge variant="pro">Pro</Badge>
      </div>
      <div className="flex items-start gap-3 px-4 pb-4 text-body-sm">
        <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5 text-primary" />
        <span className="text-text-secondary">
          Fitness/fatigue tracking (CTL/ATL/TSB) and all-time personal records are a Pro
          feature.{' '}
          <a href="/billing" className="underline font-medium text-primary">Upgrade to Pro →</a>
        </span>
      </div>
    </div>
  )
}

export function TrainingLoad() {
  const user = useAuthStore((s) => s.user)
  const isPro = isPaidTier(user?.tier)

  const { data: load, isLoading: loadingLoad } = useTrainingLoad(90, isPro)
  const { data: records, isLoading: loadingRecords } = useActivityRecords(isPro)

  if (!isPro) return <UpsellBanner />

  if (loadingLoad || loadingRecords) {
    return (
      <div className="flex items-center gap-2 text-text-secondary text-body-sm py-4 px-4 rounded-xl border border-border bg-surface">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading training load…
      </div>
    )
  }

  if (!load?.available) {
    return (
      <div className="px-4 py-4 rounded-xl border border-border bg-surface text-body-sm text-text-disabled">
        Not enough analyzed activities yet to compute training load. This fills in once your
        activities finish background analysis.
      </div>
    )
  }

  const current = load.current!
  const overall = records?.overall
  const bySport = records?.by_sport ?? {}

  return (
    <div className="rounded-xl border border-border bg-surface overflow-hidden">
      <div className="px-4 pt-3 pb-1 flex items-center justify-between gap-2">
        <span className="text-body-sm font-medium text-text-primary">Training load</span>
        <Badge variant={STATUS_BADGE[current.status]}>{STATUS_LABEL[current.status]}</Badge>
      </div>

      <div className="px-4 pb-4 space-y-4">
        <div className="grid grid-cols-3 gap-px bg-border rounded-lg overflow-hidden">
          <Tile label="Fitness (CTL)" value={current.ctl.toFixed(0)} />
          <Tile label="Fatigue (ATL)" value={current.atl.toFixed(0)} />
          <Tile label="Form (TSB)" value={current.tsb > 0 ? `+${current.tsb.toFixed(0)}` : current.tsb.toFixed(0)} />
        </div>

        <div>
          <p className="text-caption text-text-secondary mb-1.5">Fitness &amp; fatigue (90 days)</p>
          <ResponsiveContainer width="100%" height={110}>
            <LineChart data={load.series} syncId="training-load" margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
              <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 3" vertical={false} />
              <XAxis dataKey="date" hide />
              <YAxis width={32} tick={{ fill: 'var(--color-text-disabled)', fontSize: 10 }} stroke="var(--color-border)" />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                labelFormatter={(v) => new Date(v).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} formatter={(v) => <span style={{ color: 'var(--color-text-secondary)' }}>{v}</span>} />
              <Line type="monotone" dataKey="ctl" name="Fitness" stroke="var(--chart-cat-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="atl" name="Fatigue" stroke="var(--chart-cat-6)" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div>
          <p className="text-caption text-text-secondary mb-1.5">Form</p>
          <ResponsiveContainer width="100%" height={90}>
            <AreaChart data={load.series} syncId="training-load" margin={{ top: 4, right: 8, bottom: 2, left: -18 }}>
              <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 3" vertical={false} />
              <XAxis
                dataKey="date"
                tick={{ fill: 'var(--color-text-disabled)', fontSize: 10 }}
                stroke="var(--color-border)"
                tickFormatter={(v) => new Date(v).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                minTickGap={24}
              />
              <YAxis width={32} tick={{ fill: 'var(--color-text-disabled)', fontSize: 10 }} stroke="var(--color-border)" />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                labelFormatter={(v) => new Date(v).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                formatter={(v: number) => [v > 0 ? `+${v}` : v, 'TSB']}
              />
              <ReferenceLine y={0} stroke="var(--color-border-strong)" />
              <Area
                type="monotone"
                dataKey="tsb"
                stroke="var(--chart-speed)"
                fill="var(--chart-speed)"
                fillOpacity={0.15}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {overall && (
          <div>
            <p className="text-caption text-text-secondary mb-1.5">All-time records</p>
            <div className="grid sm:grid-cols-2 gap-x-6">
              <div>
                <RecordRow label="Longest distance" entry={overall.longest_distance_m} format={formatDistance} />
                <RecordRow label="Longest duration" entry={overall.longest_duration_s} format={(v) => formatDuration(Math.round(v))} />
                <RecordRow label="Most elevation gain" entry={overall.most_elevation_gain_m} format={(v) => `${Math.round(v)} m`} />
              </div>
              <div>
                <RecordRow label="Highest avg speed" entry={overall.highest_avg_speed_ms} format={(v) => `${(v * 3.6).toFixed(1)} km/h`} />
                <RecordRow label="Highest avg power" entry={overall.highest_avg_power_w} format={(v) => `${Math.round(v)} W`} />
                <RecordRow label="Highest TSS" entry={overall.highest_tss} format={(v) => `${Math.round(v)}`} />
              </div>
            </div>
          </div>
        )}

        {Object.keys(bySport).length > 0 && (
          <div>
            <p className="text-caption text-text-secondary mb-1.5">Best per sport</p>
            <div className="space-y-2">
              {Object.entries(bySport).map(([sport, recs]) => (
                <div key={sport} className="flex items-center justify-between gap-3 text-body-sm">
                  <span className="text-text-secondary">{sportLabel(sport)}</span>
                  <span className="text-text-primary tabular-nums">
                    {recs.longest_distance_m ? formatDistance(recs.longest_distance_m.value) : '—'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
