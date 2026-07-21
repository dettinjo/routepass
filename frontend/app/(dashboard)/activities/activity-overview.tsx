'use client'

import { useState } from 'react'
import { BarChart3, ChevronDown } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatDistance, formatDuration, sportLabel } from '@/lib/utils'
import { useActivitiesOverview } from '@/hooks/use-activities'
import type { ActivityFilters, OverviewSport, OverviewTrendPoint } from '@/types/api'

// Single-hue magnitude bars (distance) — sequential, not categorical: the axis
// label already carries identity, so one hue is correct here (see dataviz skill).
const BAR = 'var(--chart-speed)'
const TOOLTIP_STYLE = {
  background: 'var(--color-surface-raised)',
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  fontSize: 12,
} as const

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface-raised px-3 py-2.5 flex flex-col items-center gap-1 text-center">
      <p className="text-heading-sm text-text-primary font-semibold tabular-nums leading-none">{value}</p>
      <p className="text-[9px] font-medium text-text-disabled uppercase tracking-wider leading-none">{label}</p>
    </div>
  )
}

function SportBars({ data }: { data: OverviewSport[] }) {
  const rows = data.slice(0, 8).map((s) => ({
    name: sportLabel(s.sport_type),
    km: +(s.distance_m / 1000).toFixed(1),
  }))
  const height = Math.max(120, rows.length * 34)
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 12, bottom: 4, left: 4 }}>
        <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 3" horizontal={false} />
        <XAxis
          type="number"
          tick={{ fill: 'var(--color-text-disabled)', fontSize: 10 }}
          stroke="var(--color-border)"
          tickFormatter={(v) => `${v}`}
        />
        <YAxis
          type="category"
          dataKey="name"
          width={92}
          tick={{ fill: 'var(--color-text-secondary)', fontSize: 11 }}
          stroke="var(--color-border)"
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          cursor={{ fill: 'var(--color-border)', opacity: 0.3 }}
          formatter={(v: number) => [`${v} km`, 'Distance']}
        />
        <Bar dataKey="km" fill={BAR} radius={[0, 4, 4, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  )
}

function TrendBars({ data }: { data: OverviewTrendPoint[] }) {
  const rows = data.map((p) => ({ label: p.label, km: +(p.distance_m / 1000).toFixed(1) }))
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={rows} margin={{ top: 4, right: 8, bottom: 4, left: -12 }}>
        <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 3" vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fill: 'var(--color-text-disabled)', fontSize: 10 }}
          stroke="var(--color-border)"
          interval="preserveStartEnd"
          minTickGap={16}
        />
        <YAxis
          tick={{ fill: 'var(--color-text-disabled)', fontSize: 10 }}
          stroke="var(--color-border)"
          tickFormatter={(v) => `${v}`}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          cursor={{ fill: 'var(--color-border)', opacity: 0.3 }}
          formatter={(v: number) => [`${v} km`, 'Distance']}
        />
        <Bar dataKey="km" fill={BAR} radius={[4, 4, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function ActivityOverview({ filters }: { filters: ActivityFilters }) {
  const [open, setOpen] = useState(true)
  const { data, isLoading } = useActivitiesOverview(filters)

  // Hide entirely when there's nothing to summarise.
  if (!isLoading && (!data || data.totals.count === 0)) return null

  const t = data?.totals

  return (
    <div className="rounded-xl border border-border bg-surface overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-2 px-4 py-3 text-left hover:bg-surface-raised transition-colors"
      >
        <span className="flex items-center gap-2 text-body-sm font-medium text-text-primary">
          <BarChart3 className="w-4 h-4 text-text-secondary" />
          Overview
          {t && (
            <span className="text-text-disabled font-normal">
              · {t.count} activities · {formatDistance(t.distance_m)}
            </span>
          )}
        </span>
        <ChevronDown
          className={`w-4 h-4 text-text-secondary transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-4">
          {isLoading || !data ? (
            <div className="h-24 shimmer rounded-lg" />
          ) : (
            <>
              <div className="grid grid-cols-3 sm:grid-cols-6 gap-px bg-border rounded-lg overflow-hidden">
                <Tile label="Activities" value={String(data.totals.count)} />
                <Tile label="Distance" value={formatDistance(data.totals.distance_m)} />
                <Tile label="Moving time" value={formatDuration(Math.round(data.totals.moving_time_s || data.totals.duration_s))} />
                <Tile label="Elevation ↑" value={`${Math.round(data.totals.elevation_up_m)} m`} />
                <Tile label="Calories" value={data.totals.calories > 0 ? String(Math.round(data.totals.calories)) : '—'} />
                <Tile label="TSS" value={data.totals.tss > 0 ? String(Math.round(data.totals.tss)) : '—'} />
              </div>

              {data.totals.metrics_pending > 0 && (
                <p className="text-caption text-text-disabled">
                  {data.totals.metrics_pending} activit
                  {data.totals.metrics_pending === 1 ? 'y is' : 'ies are'} still being
                  analysed — calories &amp; TSS totals will rise as they finish.
                </p>
              )}

              <div className="grid md:grid-cols-2 gap-5">
                {data.by_sport.length > 0 && (
                  <div>
                    <p className="text-caption text-text-secondary mb-1.5">Distance by sport (km)</p>
                    <SportBars data={data.by_sport} />
                  </div>
                )}
                {data.trend.length > 1 && (
                  <div>
                    <p className="text-caption text-text-secondary mb-1.5">
                      Distance per {data.grain === 'month' ? 'month' : 'week'} (km)
                    </p>
                    <TrendBars data={data.trend} />
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
