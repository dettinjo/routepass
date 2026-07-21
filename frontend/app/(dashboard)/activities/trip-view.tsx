'use client'

import { useEffect } from 'react'
import dynamic from 'next/dynamic'
import { Loader2, X } from 'lucide-react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatDistance, formatDuration, sportLabel } from '@/lib/utils'
import { useTripAnalysis } from '@/hooks/use-activities'
import { ZoneBar } from './activity-analysis'
import { stageColorVar } from './trip-map'
import type { TripStage } from '@/types/api'

const TripMap = dynamic(() => import('./trip-map').then((m) => m.TripMap), { ssr: false })

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

function ElevationProfile({
  profile,
  stages,
}: {
  profile: { x: number | null; ele: number | null; stage: number }[]
  stages: TripStage[]
}) {
  const data = profile.filter((p) => p.x != null)
  if (data.length < 2) return null

  const boundaries = stages
    .slice(1)
    .map((s, i) => ({ x: s.cumulative_distance_start_m / 1000, stage: i + 1 }))

  return (
    <ResponsiveContainer width="100%" height={140}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 2, left: -18 }}>
        <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 3" vertical={false} />
        <XAxis
          dataKey="x"
          type="number"
          domain={['dataMin', 'dataMax']}
          tick={{ fill: 'var(--color-text-disabled)', fontSize: 10 }}
          stroke="var(--color-border)"
          tickFormatter={(v) => `${Math.round(v)}`}
        />
        <YAxis
          width={40}
          tick={{ fill: 'var(--color-text-disabled)', fontSize: 10 }}
          stroke="var(--color-border)"
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelFormatter={(v) => `${(+v).toFixed(1)} km`}
          formatter={(v: number) => [`${Math.round(v)} m`, 'Elevation']}
        />
        {boundaries.map((b) => (
          <ReferenceLine
            key={b.stage}
            x={b.x}
            stroke={stageColorVar(b.stage)}
            strokeDasharray="3 3"
            strokeWidth={1.5}
          />
        ))}
        <Area
          type="monotone"
          dataKey="ele"
          stroke="var(--chart-elevation)"
          fill="var(--chart-elevation)"
          fillOpacity={0.15}
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
          connectNulls
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

function DayBars({ days }: { days: { date: string; distance_m: number }[] }) {
  const rows = days.map((d) => ({
    label: new Date(d.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    km: +(d.distance_m / 1000).toFixed(1),
  }))
  return (
    <ResponsiveContainer width="100%" height={140}>
      <BarChart data={rows} margin={{ top: 4, right: 8, bottom: 2, left: -18 }}>
        <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 3" vertical={false} />
        <XAxis dataKey="label" tick={{ fill: 'var(--color-text-disabled)', fontSize: 10 }} stroke="var(--color-border)" />
        <YAxis tick={{ fill: 'var(--color-text-disabled)', fontSize: 10 }} stroke="var(--color-border)" />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          cursor={{ fill: 'var(--color-border)', opacity: 0.3 }}
          formatter={(v: number) => [`${v} km`, 'Distance']}
        />
        <Bar dataKey="km" fill="var(--chart-speed)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  )
}

function StageTable({ stages }: { stages: TripStage[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-body-sm">
        <thead>
          <tr className="text-left text-caption text-text-disabled border-b border-border">
            <th className="pb-1.5 pr-3"></th>
            <th className="pb-1.5 pr-3">Stage</th>
            <th className="pb-1.5 pr-3">Date</th>
            <th className="pb-1.5 pr-3">Distance</th>
            <th className="pb-1.5 pr-3">Time</th>
            <th className="pb-1.5 pr-3">Elev↑</th>
            <th className="pb-1.5">HR / Power</th>
          </tr>
        </thead>
        <tbody>
          {stages.map((s, i) => (
            <tr key={s.id} className="border-b border-border last:border-0">
              <td className="py-1.5 pr-3">
                <span
                  className="inline-block w-2.5 h-2.5 rounded-full"
                  style={{ background: stageColorVar(i) }}
                  aria-hidden
                />
              </td>
              <td className="py-1.5 pr-3 text-text-primary">
                {s.name ?? 'Untitled'}
                {s.sport_type && (
                  <span className="text-text-disabled"> · {sportLabel(s.sport_type)}</span>
                )}
              </td>
              <td className="py-1.5 pr-3 text-text-secondary tabular-nums">
                {s.started_at ? new Date(s.started_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '—'}
              </td>
              <td className="py-1.5 pr-3 text-text-secondary tabular-nums">
                {s.distance_m != null ? formatDistance(s.distance_m) : '—'}
              </td>
              <td className="py-1.5 pr-3 text-text-secondary tabular-nums">
                {s.duration_s != null ? formatDuration(s.duration_s) : '—'}
              </td>
              <td className="py-1.5 pr-3 text-text-secondary tabular-nums">
                {s.elevation_gain_m != null ? `${Math.round(s.elevation_gain_m)} m` : '—'}
              </td>
              <td className="py-1.5 text-text-secondary tabular-nums">
                {s.avg_hr != null ? `${Math.round(s.avg_hr)} bpm` : '—'}
                {s.avg_power != null ? ` / ${Math.round(s.avg_power)} W` : ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function TripView({ activityIds, onClose }: { activityIds: string[]; onClose: () => void }) {
  const { mutate, data, isPending, isError, error } = useTripAnalysis()

  useEffect(() => {
    mutate(activityIds)
    // Only re-run if the underlying selection identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activityIds.join(',')])

  const mapStages = data?.map_stages.map((ms) => ({
    ...ms,
    name: data.stages[ms.stage]?.name ?? ms.name,
  }))

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/50" onClick={onClose}>
      <div
        className="w-full max-w-2xl bg-bg border border-border rounded-xl shadow-xl animate-in fade-in slide-in-from-bottom-4 overflow-y-auto max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 px-6 pt-5 pb-4 border-b border-border">
          <div>
            <h2 className="text-heading-sm text-text-primary font-semibold leading-tight">Trip analysis</h2>
            <p className="text-body-sm text-text-secondary mt-0.5">
              {activityIds.length} activities combined
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 p-1.5 rounded-md hover:bg-surface-raised text-text-secondary hover:text-text-primary transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-6 py-5 space-y-5">
          {isPending && (
            <div className="flex items-center gap-2 text-text-secondary text-body-sm py-6 justify-center">
              <Loader2 className="w-4 h-4 animate-spin" /> Combining stages…
            </div>
          )}

          {isError && (
            <p className="text-body-sm text-error py-4">
              {error instanceof Error ? error.message : 'Failed to analyze trip.'}
            </p>
          )}

          {data && (
            <>
              <div className="grid grid-cols-3 sm:grid-cols-6 gap-px bg-border rounded-lg overflow-hidden">
                <Tile label="Stages" value={String(data.totals.count)} />
                <Tile label="Distance" value={formatDistance(data.totals.distance_m)} />
                <Tile label="Moving time" value={formatDuration(Math.round(data.totals.moving_time_s || data.totals.duration_s))} />
                <Tile label="Elevation ↑" value={`${Math.round(data.totals.elevation_gain_m)} m`} />
                <Tile label="Calories" value={data.totals.calories > 0 ? String(Math.round(data.totals.calories)) : '—'} />
                <Tile label="TSS" value={data.totals.tss > 0 ? String(Math.round(data.totals.tss)) : '—'} />
              </div>

              {mapStages && mapStages.length > 0 && <TripMap stages={mapStages} />}

              {data.profile.length > 1 && (
                <div>
                  <p className="text-caption text-text-secondary mb-1.5">
                    Elevation profile <span className="text-text-disabled">(km, dashed lines mark stage boundaries)</span>
                  </p>
                  <ElevationProfile profile={data.profile} stages={data.stages} />
                </div>
              )}

              {data.day_bars.length > 1 && (
                <div>
                  <p className="text-caption text-text-secondary mb-1.5">Distance per day</p>
                  <DayBars days={data.day_bars} />
                </div>
              )}

              {(data.hr_zones || data.power_zones) && (
                <div className="space-y-3">
                  {data.hr_zones && <ZoneBar title="Combined time in HR zones" zones={data.hr_zones} prefix="Z" />}
                  {data.power_zones && <ZoneBar title="Combined time in power zones" zones={data.power_zones} prefix="Z" />}
                </div>
              )}

              <div>
                <p className="text-caption text-text-secondary mb-1.5">Stages</p>
                <StageTable stages={data.stages} />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
