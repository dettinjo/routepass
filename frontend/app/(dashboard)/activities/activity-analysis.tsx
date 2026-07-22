'use client'

import { Loader2 } from 'lucide-react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatDuration } from '@/lib/utils'
import { useActivityMetrics, useActivityTrack } from '@/hooks/use-activity-analysis'
import type {
  ActivityDecoupling,
  ActivityMetricsSummary,
  ActivityTrackPoint,
  ActivityZones,
} from '@/types/api'

// One panel per metric — never a dual-axis chart. Each is a single series, so it
// needs no legend (the panel title names it). syncId ties a shared crosshair
// across every panel. Colors come from the validated chart tokens in globals.css.
interface PanelDef {
  key: 'ele' | 'hr' | 'power' | 'speed' | 'cad'
  label: string
  unit: string
  color: string
  area?: boolean
  needs: string // metrics_available flag that must be present
}

const PANELS: PanelDef[] = [
  { key: 'ele', label: 'Elevation', unit: 'm', color: 'var(--chart-elevation)', area: true, needs: 'elevation' },
  { key: 'hr', label: 'Heart rate', unit: 'bpm', color: 'var(--chart-hr)', needs: 'heartrate' },
  { key: 'power', label: 'Power', unit: 'W', color: 'var(--chart-power)', area: true, needs: 'power' },
  { key: 'speed', label: 'Speed', unit: 'km/h', color: 'var(--chart-speed)', needs: 'distance' },
  { key: 'cad', label: 'Cadence', unit: 'rpm', color: 'var(--chart-cadence)', needs: 'cadence' },
]

const ZONE_COLORS = [
  'var(--chart-zone-1)',
  'var(--chart-zone-2)',
  'var(--chart-zone-3)',
  'var(--chart-zone-4)',
  'var(--chart-zone-5)',
  'var(--chart-zone-6)',
  'var(--chart-zone-7)',
]

// Tiles that complement (never duplicate) the modal's top stat grid, which
// already shows distance / duration / elevation gain / avg+max speed.
function buildTiles(
  s: ActivityMetricsSummary,
  tssMethod: 'power' | 'hr_estimate' | undefined,
): { label: string; value: string }[] {
  const tiles: { label: string; value: string }[] = []
  const push = (label: string, v: string | null) => {
    if (v != null) tiles.push({ label, value: v })
  }
  push('Moving time', s.moving_time_s != null ? formatDuration(Math.round(s.moving_time_s)) : null)
  push('Elevation ↓', s.elevation_loss_m != null ? `${Math.round(s.elevation_loss_m)} m` : null)
  push('Calories', s.calories != null ? `${Math.round(s.calories)}` : null)
  push('Avg HR', s.avg_hr != null ? `${Math.round(s.avg_hr)} bpm` : null)
  push('Max HR', s.max_hr != null ? `${Math.round(s.max_hr)} bpm` : null)
  push('Avg power', s.avg_power != null ? `${Math.round(s.avg_power)} W` : null)
  push('Max power', s.max_power != null ? `${Math.round(s.max_power)} W` : null)
  push('Norm. power', s.normalized_power != null ? `${Math.round(s.normalized_power)} W` : null)
  push('TSS' + (tssMethod === 'hr_estimate' ? ' (est.)' : ''), s.tss != null ? `${Math.round(s.tss)}` : null)
  push('Avg cadence', s.avg_cadence != null ? `${Math.round(s.avg_cadence)} rpm` : null)
  return tiles
}

function DecouplingNote({ decoupling }: { decoupling: ActivityDecoupling }) {
  const drifted = decoupling.pct >= 5
  return (
    <p className="text-caption text-text-secondary">
      Aerobic decoupling ({decoupling.metric === 'power' ? 'Pw:Hr' : 'Pa:Hr'}):{' '}
      <span className={drifted ? 'text-warning font-medium' : 'text-text-primary font-medium'}>
        {decoupling.pct > 0 ? '+' : ''}
        {decoupling.pct}%
      </span>
      {drifted && ' — noticeable cardiac drift'}
    </p>
  )
}

function buildData(points: ActivityTrackPoint[], hasDistance: boolean) {
  return points.map((p) => ({
    x: hasDistance && p.d != null ? p.d / 1000 : p.t / 60,
    ele: p.ele,
    hr: p.hr,
    power: p.power,
    speed: p.speed != null ? p.speed * 3.6 : null,
    cad: p.cad,
  }))
}

function ProfilePanel({
  panel,
  data,
  xUnit,
  showAxis,
}: {
  panel: PanelDef
  data: Record<string, number | null>[]
  xUnit: string
  showAxis: boolean
}) {
  const Chart = panel.area ? AreaChart : LineChart
  return (
    <div>
      <p className="text-caption text-text-secondary mb-1 flex items-center gap-1.5">
        <span
          className="inline-block w-2.5 h-2.5 rounded-full"
          style={{ background: panel.color }}
          aria-hidden
        />
        {panel.label} <span className="text-text-disabled">({panel.unit})</span>
      </p>
      <ResponsiveContainer width="100%" height={showAxis ? 96 : 76}>
        <Chart data={data} syncId="activity-profile" margin={{ top: 4, right: 6, bottom: showAxis ? 2 : 0, left: -18 }}>
          <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 3" vertical={false} />
          <XAxis
            dataKey="x"
            hide={!showAxis}
            tickFormatter={(v) => `${Math.round(v)}`}
            tick={{ fill: 'var(--color-text-disabled)', fontSize: 10 }}
            stroke="var(--color-border)"
            label={
              showAxis
                ? { value: xUnit, position: 'insideBottomRight', offset: -2, fill: 'var(--color-text-disabled)', fontSize: 10 }
                : undefined
            }
          />
          <YAxis
            width={40}
            tick={{ fill: 'var(--color-text-disabled)', fontSize: 10 }}
            stroke="var(--color-border)"
            domain={['auto', 'auto']}
            tickCount={4}
          />
          <Tooltip
            contentStyle={{
              background: 'var(--color-surface-raised)',
              border: '1px solid var(--color-border)',
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: 'var(--color-text-secondary)' }}
            itemStyle={{ color: 'var(--color-text-primary)' }}
            labelFormatter={(v) => `${(+v).toFixed(1)} ${xUnit}`}
            formatter={(value: number) => [
              `${Math.round(value)} ${panel.unit}`,
              panel.label,
            ]}
          />
          {panel.area ? (
            <Area
              type="monotone"
              dataKey={panel.key}
              stroke={panel.color}
              fill={panel.color}
              fillOpacity={0.15}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
          ) : (
            <Line
              type="monotone"
              dataKey={panel.key}
              stroke={panel.color}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
          )}
        </Chart>
      </ResponsiveContainer>
    </div>
  )
}

export function ZoneBar({ title, zones, prefix }: { title: string; zones: ActivityZones; prefix: string }) {
  const total = zones.seconds.reduce((a, b) => a + b, 0)
  if (total <= 0) return null
  return (
    <div>
      <p className="text-caption text-text-secondary mb-1.5">{title}</p>
      <div className="flex h-6 rounded-md overflow-hidden gap-px bg-border">
        {zones.seconds.map((s, i) => {
          const pct = (s / total) * 100
          if (pct < 0.5) return null
          return (
            <div
              key={i}
              className="flex items-center justify-center text-[9px] font-medium text-white/90"
              style={{ width: `${pct}%`, background: ZONE_COLORS[i] ?? ZONE_COLORS[0] }}
              title={`${prefix}${i + 1}: ${formatDuration(Math.round(s))} (${pct.toFixed(0)}%)`}
            >
              {pct > 8 ? `${prefix}${i + 1}` : ''}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function ActivityAnalysis({ activityId }: { activityId: string }) {
  const { data: metrics } = useActivityMetrics(activityId)
  const { data: track } = useActivityTrack(activityId)

  if (!metrics) {
    return (
      <div className="flex items-center gap-2 text-text-secondary text-body-sm py-4 px-6">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading analysis…
      </div>
    )
  }

  if (!metrics.computed) {
    return (
      <div className="flex items-center gap-2 text-text-secondary text-body-sm py-4 px-6">
        <Loader2 className="w-4 h-4 animate-spin" />
        Analyzing track… this runs in the background and will appear shortly.
      </div>
    )
  }

  const available = metrics.available
  const points = track?.points ?? []
  const hasDistance = available.includes('distance')
  const data = buildData(points, hasDistance)
  const xUnit = hasDistance ? 'km' : 'min'

  const activePanels = PANELS.filter(
    (p) => available.includes(p.needs) && data.some((d) => d[p.key] != null),
  )

  const hrZones = metrics.detail.hr_zones
  const powerZones = metrics.detail.power_zones
  const splits = metrics.detail.splits ?? []
  const decoupling = metrics.detail.decoupling
  const tiles = buildTiles(metrics.summary, metrics.detail.tss_method)

  return (
    <div className="px-6 pb-5 space-y-5">
      {/* Enriched metric tiles (complement the top stat grid) */}
      {tiles.length > 0 && (
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-px bg-border rounded-xl overflow-hidden">
          {tiles.map(({ label, value }) => (
            <div key={label} className="bg-surface-raised px-2 py-2.5 flex flex-col items-center gap-1 text-center">
              <p className="text-body-sm text-text-primary font-semibold tabular-nums leading-none">{value}</p>
              <p className="text-[9px] font-medium text-text-disabled uppercase tracking-wider leading-none">{label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Synced profile panels */}
      {points.length > 1 && activePanels.length > 0 && (
        <div className="space-y-3">
          {activePanels.map((panel, i) => (
            <ProfilePanel
              key={panel.key}
              panel={panel}
              data={data}
              xUnit={xUnit}
              showAxis={i === activePanels.length - 1}
            />
          ))}
        </div>
      )}

      {decoupling && <DecouplingNote decoupling={decoupling} />}

      {/* Zones */}
      {(hrZones || powerZones) && (
        <div className="space-y-3">
          {hrZones && <ZoneBar title="Time in heart-rate zones" zones={hrZones} prefix="Z" />}
          {powerZones && <ZoneBar title="Time in power zones" zones={powerZones} prefix="Z" />}
        </div>
      )}

      {/* Splits */}
      {splits.length > 1 && (
        <div>
          <p className="text-caption text-text-secondary mb-1.5">Splits (per km)</p>
          <div className="overflow-x-auto">
            <table className="w-full text-body-sm">
              <thead>
                <tr className="text-left text-caption text-text-disabled border-b border-border">
                  <th className="pb-1 pr-3">#</th>
                  <th className="pb-1 pr-3">Pace</th>
                  <th className="pb-1 pr-3">Elev↑</th>
                  {splits[0].avg_hr != null && <th className="pb-1 pr-3">HR</th>}
                  {splits[0].avg_power != null && <th className="pb-1">Power</th>}
                </tr>
              </thead>
              <tbody>
                {splits.map((s) => {
                  const paceSecPerKm = s.speed_ms && s.speed_ms > 0 ? 1000 / s.speed_ms : null
                  const pace =
                    paceSecPerKm != null
                      ? `${Math.floor(paceSecPerKm / 60)}:${String(Math.round(paceSecPerKm % 60)).padStart(2, '0')}/km`
                      : '—'
                  return (
                    <tr key={s.index} className="border-b border-border last:border-0">
                      <td className="py-1 pr-3 text-text-secondary">{s.index}</td>
                      <td className="py-1 pr-3 text-text-primary tabular-nums">{pace}</td>
                      <td className="py-1 pr-3 text-text-secondary tabular-nums">
                        {Math.round(s.elevation_gain_m)} m
                      </td>
                      {s.avg_hr != null && (
                        <td className="py-1 pr-3 text-text-secondary tabular-nums">
                          {Math.round(s.avg_hr)}
                        </td>
                      )}
                      {s.avg_power != null && (
                        <td className="py-1 text-text-secondary tabular-nums">
                          {Math.round(s.avg_power)} W
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {points.length <= 1 && !hrZones && !powerZones && splits.length === 0 && (
        <p className="text-body-sm text-text-disabled">
          No detailed track data available for this activity.
        </p>
      )}
    </div>
  )
}
