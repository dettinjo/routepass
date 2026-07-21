'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  ArrowDownAZ,
  ArrowDownWideNarrow,
  ArrowRight,
  ArrowUpDown,
  ArrowUpNarrowWide,
  CheckCircle2,
  CheckSquare,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Database,
  Filter,
  Gauge,
  Layers,
  Loader2,
  RefreshCw,
  Ruler,
  Search,
  TrendingUp,
  Trash2,
  Upload,
  X,
  Zap,
} from 'lucide-react'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Alert } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { BrandIcon } from '@/components/brand-box'
import { SportIcon } from '@/components/sport-icon'
import { PLATFORM_LABELS } from '@/components/platform-icons'
import sportMappings from '../../../../shared/sport-mappings.json'
import type { PlatformKey } from '@/components/platform-icons'
import { getBrand } from '@/lib/brand-registry'
import { useAuthStore } from '@/store/auth'
import {
  useActivities,
  useActivityIds,
  useBulkSyncActivities,
  useClearSeedActivities,
  useDeleteActivity,
  useImportGpx,
  useSeedActivities,
  useSyncActivity,
  useTriggerSync,
} from '@/hooks/use-activities'
import { useSyncStatus } from '@/hooks/use-sync-status'
import { formatDistance, formatDuration, formatRelative, sportLabel } from '@/lib/utils'
import dynamic from 'next/dynamic'
import type { Activity, ActivityFilters, UserMe } from '@/types/api'
import { parseGpxPoints } from './gpx-utils'

// Leaflet must never run on the server. `next/dynamic` with `ssr: false` ensures
// the entire activity-map module (and its `import('leaflet')` call) is excluded
// from SSR and the initial JS bundle, eliminating the ChunkLoadError.
// Only rendered inside the detail modal; lazy-load so recharts stays out of the
// initial /activities bundle.
const ActivityAnalysis = dynamic(
  () => import('./activity-analysis').then((m) => m.ActivityAnalysis),
  { ssr: false },
)

// Lazy-loaded (recharts) so the overview panel doesn't weigh down the list.
const ActivityOverview = dynamic(
  () => import('./activity-overview').then((m) => m.ActivityOverview),
  { ssr: false },
)

const ActivityMap = dynamic(
  () => import('./activity-map').then((m) => m.ActivityMap),
  {
    ssr: false,
    loading: () => (
      <div
        className="w-full rounded-lg bg-muted animate-pulse border border-border"
        style={{ height: 260 }}
      />
    ),
  }
)

const PAGE_SIZE = 25

// ── Sort / Group types ────────────────────────────────────────────────────────

type SortField = 'date' | 'distance' | 'duration' | 'elevation' | 'name'
type SortDir   = 'asc' | 'desc'
interface SortConfig { field: SortField; dir: SortDir }
type GroupBy = 'none' | 'month' | 'sport' | 'source'

const SORT_OPTIONS: { label: string; field: SortField; icon: React.ReactNode }[] = [
  { label: 'Date',      field: 'date',      icon: <Clock className="w-3.5 h-3.5" /> },
  { label: 'Distance',  field: 'distance',  icon: <ArrowDownWideNarrow className="w-3.5 h-3.5" /> },
  { label: 'Duration',  field: 'duration',  icon: <ArrowDownWideNarrow className="w-3.5 h-3.5" /> },
  { label: 'Elevation', field: 'elevation', icon: <ArrowUpNarrowWide className="w-3.5 h-3.5" /> },
  { label: 'Name',      field: 'name',      icon: <ArrowDownAZ className="w-3.5 h-3.5" /> },
]

const GROUP_OPTIONS: { label: string; value: GroupBy }[] = [
  { label: 'No grouping', value: 'none'  },
  { label: 'By month',    value: 'month' },
  { label: 'By sport',    value: 'sport' },
  { label: 'By source',   value: 'source' },
]

// ── Platform helpers ──────────────────────────────────────────────────────────

function resolveOnKomoot(act: Activity): boolean {
  return (
    act.platforms.includes('komoot') ||
    Boolean(act.komoot_tour_id && !act.komoot_tour_id.startsWith('seed_'))
  )
}
function resolveOnStrava(act: Activity): boolean {
  return act.platforms.includes('strava') || Boolean(act.strava_activity_id)
}

function activityOnPlatform(act: Activity, platform: PlatformKey): boolean {
  if (platform === 'komoot') return resolveOnKomoot(act)
  if (platform === 'strava') return resolveOnStrava(act)
  return act.platforms.includes(platform)
}

function getConnectedPlatforms(user: UserMe | null): PlatformKey[] {
  if (!user) return []
  const result: PlatformKey[] = []
  if (user.komoot_connected)    result.push('komoot')
  if (user.strava_connected)    result.push('strava')
  if (user.intervals_connected) result.push('intervals_icu')
  if (user.runalyze_connected)  result.push('runalyze')
  if (user.polar_connected)     result.push('polar')
  return result
}

// ── Compact platform presence strip ──────────────────────────────────────────
// Shows all connected platforms; present ones are opaque, absent ones are dim

function PlatformStrip({
  act,
  connectedPlatforms,
}: {
  act: Activity
  connectedPlatforms: PlatformKey[]
}) {
  if (connectedPlatforms.length === 0) return null

  return (
    <div className="flex items-center gap-1 flex-shrink-0">
      {connectedPlatforms.map((p) => {
        const present = activityOnPlatform(act, p)
        const failed  = !present && act.sync_status === 'failed'
        const brand   = getBrand(p)
        return (
          <span
            key={p}
            title={present ? `On ${brand.name}` : failed ? `Sync to ${brand.name} failed` : `Not on ${brand.name}`}
            className="relative flex items-center justify-center w-5 h-5 transition-opacity"
            style={{ opacity: present ? 1 : 0.18 }}
          >
            <BrandIcon brand={p} size={14} variant={present ? 'regular' : 'white'} />
            {present && (
              <span
                className="absolute -bottom-0.5 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full"
                style={{ backgroundColor: brand.colors.primary }}
              />
            )}
          </span>
        )
      })}
    </div>
  )
}

// ── Date presets ─────────────────────────────────────────────────────────────

type DatePreset = '7d' | '30d' | '90d' | '1y' | 'all'

const DATE_PRESETS: { label: string; value: DatePreset }[] = [
  { label: '7d',  value: '7d'  },
  { label: '30d', value: '30d' },
  { label: '90d', value: '90d' },
  { label: 'Year', value: '1y' },
  { label: 'All',  value: 'all' },
]

function presetToDateFrom(preset: DatePreset): string | undefined {
  const now = new Date()
  if (preset === 'all') return undefined
  const d = new Date(now)
  if (preset === '7d')  d.setDate(d.getDate() - 7)
  else if (preset === '30d') d.setDate(d.getDate() - 30)
  else if (preset === '90d') d.setDate(d.getDate() - 90)
  else if (preset === '1y')  d.setMonth(0, 1)
  d.setHours(0, 0, 0, 0)
  return d.toISOString()
}

// ── Sport types ───────────────────────────────────────────────────────────────

const ALL_SPORT_TYPES = [
  'touringbicycle', 'road_cycling', 'racebike', 'citybike',
  'mtb', 'mtb_easy', 'mtb_advanced', 'mountainbike', 'singletrack', 'downhillbike',
  'e_touringbicycle', 'e_road_cycling', 'e_mtb',
  'jogging', 'running', 'trail_running', 'walking', 'nordic_walking',
  'hiking', 'hike',
  'skitouring', 'skitour', 'snowshoe', 'nordic_ski', 'crosscountryskiing',
  'swimming', 'kayaking', 'canoeing', 'rowing',
  'climbing', 'yoga',
]

// ── Shared dropdown primitive ─────────────────────────────────────────────────

function useDropdown() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [open])

  return { open, setOpen, ref }
}

// ── Filter dropdown ────────────────────────────────────────────────────────────

interface FilterDropdownProps {
  filters: ActivityFilters
  connectedPlatforms: PlatformKey[]
  onFilterChange: (patch: Partial<ActivityFilters>) => void
  onClear: () => void
}

function FilterDropdown({ filters, connectedPlatforms, onFilterChange, onClear }: FilterDropdownProps) {
  const { open, setOpen, ref } = useDropdown()

  const activeCount = Object.keys(filters).filter(
    (k) => k !== 'date_from' && k !== 'date_to' && filters[k as keyof ActivityFilters] !== undefined,
  ).length + (filters.date_from ? 1 : 0)

  const STATUS_OPTIONS = [
    { label: 'Synced',     synced: true },
    { label: 'Not synced', synced: false },
    { label: 'Failed',     status: 'failed' as const },
  ]

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1.5 h-8 px-3 rounded-md border text-body-sm font-medium transition-colors ${
          activeCount > 0
            ? 'border-primary/60 bg-primary/10 text-primary'
            : 'border-border bg-surface text-text-secondary hover:border-border-strong hover:text-text-primary'
        }`}
      >
        <Filter className="w-3.5 h-3.5" />
        Filter
        {activeCount > 0 && (
          <span className="flex items-center justify-center w-4 h-4 rounded-full bg-primary text-[10px] font-bold text-white">
            {activeCount}
          </span>
        )}
        <ChevronDown className="w-3 h-3 ml-0.5 opacity-50" />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1.5 w-72 bg-surface border border-border rounded-xl shadow-lg z-30 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
            <span className="text-body-sm font-semibold text-text-primary">Filters</span>
            {activeCount > 0 && (
              <button
                onClick={() => { onClear(); setOpen(false) }}
                className="text-caption text-text-disabled hover:text-primary transition-colors"
              >
                Clear all
              </button>
            )}
          </div>

          <div className="p-4 space-y-5">
            {/* Source — only show if user has connected platforms */}
            {connectedPlatforms.length > 0 && (
              <div>
                <p className="text-label text-text-disabled uppercase tracking-wider mb-2">Source</p>
                <div className="flex flex-wrap gap-1.5">
                  {(['komoot', 'strava', 'import'] as const).map((src) => {
                    const isConn = src === 'import' || connectedPlatforms.includes(src)
                    if (!isConn) return null
                    const active = filters.source === src
                    const brand  = src !== 'import' ? getBrand(src) : null
                    return (
                      <button
                        key={src}
                        onClick={() => onFilterChange({ source: active ? undefined : src })}
                        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-body-sm font-medium transition-all ${
                          active
                            ? 'border-primary/60 bg-primary/10 text-primary'
                            : 'border-border bg-surface-raised text-text-secondary hover:border-border-strong hover:text-text-primary'
                        }`}
                      >
                        {brand ? (
                          <BrandIcon brand={src as PlatformKey} size={13} variant={active ? 'regular' : 'white'} />
                        ) : (
                          <span className="w-3 h-3 rounded-sm bg-current opacity-50" />
                        )}
                        {src === 'import' ? 'Local / GPX' : PLATFORM_LABELS[src as PlatformKey]}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Sync status */}
            <div>
              <p className="text-label text-text-disabled uppercase tracking-wider mb-2">Sync status</p>
              <div className="flex flex-wrap gap-1.5">
                {STATUS_OPTIONS.map((opt) => {
                  const active = opt.status
                    ? filters.sync_status === opt.status
                    : filters.synced === opt.synced
                  return (
                    <button
                      key={opt.label}
                      onClick={() => {
                        if (opt.status) {
                          onFilterChange({ sync_status: active ? undefined : opt.status, synced: undefined })
                        } else {
                          onFilterChange({ synced: active ? undefined : opt.synced, sync_status: undefined })
                        }
                      }}
                      className={`px-2.5 py-1.5 rounded-lg border text-body-sm font-medium transition-all ${
                        active
                          ? 'border-primary/60 bg-primary/10 text-primary'
                          : 'border-border bg-surface-raised text-text-secondary hover:border-border-strong hover:text-text-primary'
                      }`}
                    >
                      {opt.label}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Sport type */}
            <div>
              <p className="text-label text-text-disabled uppercase tracking-wider mb-2">Sport type</p>
              <select
                value={filters.sport_type ?? ''}
                onChange={(e) => onFilterChange({ sport_type: e.target.value || undefined })}
                className="w-full h-8 px-2 pr-6 rounded-lg border border-border bg-surface-raised text-body-sm text-text-primary focus:outline-none focus:border-primary appearance-none cursor-pointer"
              >
                <option value="">All sports</option>
                {ALL_SPORT_TYPES.map((st) => (
                  <option key={st} value={st}>{sportLabel(st)}</option>
                ))}
              </select>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Sort dropdown ─────────────────────────────────────────────────────────────

function SortDropdown({
  sort,
  onSort,
}: {
  sort: SortConfig
  onSort: (s: SortConfig) => void
}) {
  const { open, setOpen, ref } = useDropdown()
  const isDefault = sort.field === 'date' && sort.dir === 'desc'
  const current = SORT_OPTIONS.find((o) => o.field === sort.field)

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1.5 h-8 px-3 rounded-md border text-body-sm font-medium transition-colors ${
          !isDefault
            ? 'border-primary/60 bg-primary/10 text-primary'
            : 'border-border bg-surface text-text-secondary hover:border-border-strong hover:text-text-primary'
        }`}
      >
        <ArrowUpDown className="w-3.5 h-3.5" />
        {!isDefault ? current?.label : 'Sort'}
        {!isDefault && (
          <span className="text-caption opacity-70">{sort.dir === 'asc' ? '↑' : '↓'}</span>
        )}
        <ChevronDown className="w-3 h-3 ml-0.5 opacity-50" />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1.5 w-52 bg-surface border border-border rounded-xl shadow-lg z-30 overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <span className="text-body-sm font-semibold text-text-primary">Sort by</span>
          </div>
          <div className="p-1.5">
            {SORT_OPTIONS.map((opt) => {
              const selected = sort.field === opt.field
              const nextDir  = selected ? (sort.dir === 'desc' ? 'asc' : 'desc') : 'desc'
              return (
                <button
                  key={opt.field}
                  onClick={() => { onSort({ field: opt.field, dir: nextDir }); setOpen(false) }}
                  className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-body-sm transition-colors ${
                    selected
                      ? 'bg-primary/10 text-primary'
                      : 'text-text-secondary hover:bg-surface-raised hover:text-text-primary'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {opt.icon}
                    {opt.label}
                  </div>
                  {selected && (
                    <span className="text-caption">{sort.dir === 'asc' ? '↑ Asc' : '↓ Desc'}</span>
                  )}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Group-by dropdown ─────────────────────────────────────────────────────────

function GroupDropdown({
  groupBy,
  onGroupBy,
}: {
  groupBy: GroupBy
  onGroupBy: (g: GroupBy) => void
}) {
  const { open, setOpen, ref } = useDropdown()
  const isDefault = groupBy === 'none'

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1.5 h-8 px-3 rounded-md border text-body-sm font-medium transition-colors ${
          !isDefault
            ? 'border-primary/60 bg-primary/10 text-primary'
            : 'border-border bg-surface text-text-secondary hover:border-border-strong hover:text-text-primary'
        }`}
      >
        <Layers className="w-3.5 h-3.5" />
        {isDefault ? 'Group' : GROUP_OPTIONS.find((o) => o.value === groupBy)?.label}
        <ChevronDown className="w-3 h-3 ml-0.5 opacity-50" />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1.5 w-48 bg-surface border border-border rounded-xl shadow-lg z-30 overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <span className="text-body-sm font-semibold text-text-primary">Group by</span>
          </div>
          <div className="p-1.5">
            {GROUP_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => { onGroupBy(opt.value); setOpen(false) }}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-body-sm transition-colors ${
                  groupBy === opt.value
                    ? 'bg-primary/10 text-primary'
                    : 'text-text-secondary hover:bg-surface-raised hover:text-text-primary'
                }`}
              >
                {opt.label}
                {groupBy === opt.value && <CheckCircle2 className="w-3.5 h-3.5" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Toolbar ───────────────────────────────────────────────────────────────────

interface ToolbarProps {
  searchInput: string
  filters: ActivityFilters
  sort: SortConfig
  groupBy: GroupBy
  datePreset: DatePreset
  connectedPlatforms: PlatformKey[]
  isSyncing: boolean
  syncedAt: string | null
  selectionMode: boolean
  onSearchChange: (v: string) => void
  onFilterChange: (patch: Partial<ActivityFilters>) => void
  onClearFilters: () => void
  onSort: (s: SortConfig) => void
  onGroupBy: (g: GroupBy) => void
  onDatePreset: (p: DatePreset) => void
  onRefresh: () => void
  onToggleSelect: () => void
  onImport: () => void
}

function Toolbar({
  searchInput, filters, sort, groupBy, datePreset,
  connectedPlatforms, isSyncing, syncedAt, selectionMode,
  onSearchChange, onFilterChange, onClearFilters, onSort, onGroupBy,
  onDatePreset, onRefresh, onToggleSelect, onImport,
}: ToolbarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 px-1 pb-4">
      {/* Search */}
      <div className="relative w-56 flex-shrink-0">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-disabled pointer-events-none" />
        <Input
          className="pl-8 h-8 text-body-sm"
          placeholder="Search activities…"
          value={searchInput}
          onChange={(e) => onSearchChange(e.target.value)}
        />
        {searchInput && (
          <button
            onClick={() => onSearchChange('')}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-text-disabled hover:text-text-primary"
          >
            <X className="w-3 h-3" />
          </button>
        )}
      </div>

      {/* Filter / Sort / Group */}
      <div className="flex items-center gap-1.5">
        <FilterDropdown
          filters={filters}
          connectedPlatforms={connectedPlatforms}
          onFilterChange={onFilterChange}
          onClear={onClearFilters}
        />
        <SortDropdown sort={sort} onSort={onSort} />
        <GroupDropdown groupBy={groupBy} onGroupBy={onGroupBy} />
      </div>

      <div className="w-px h-5 bg-border hidden sm:block" />

      {/* Period pills */}
      <div className="flex items-center gap-1">
        {DATE_PRESETS.map((p) => (
          <button
            key={p.value}
            onClick={() => onDatePreset(p.value)}
            className={`px-2.5 py-1 rounded-full text-caption font-medium transition-colors ${
              datePreset === p.value
                ? 'bg-primary text-white'
                : 'bg-surface text-text-secondary border border-border hover:border-primary/40 hover:text-text-primary'
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Refresh */}
      <button
        onClick={onRefresh}
        disabled={isSyncing}
        title={syncedAt ? `Last synced ${formatRelative(new Date(syncedAt))}` : 'Refresh'}
        className={`flex items-center gap-1.5 h-8 px-2 rounded-md border border-border bg-surface text-text-secondary hover:border-border-strong hover:text-text-primary transition-colors disabled:opacity-50 ${
          isSyncing ? 'cursor-not-allowed' : ''
        }`}
      >
        <RefreshCw className={`w-3.5 h-3.5 ${isSyncing ? 'animate-spin' : ''}`} />
        {isSyncing && <span className="text-caption hidden sm:inline">Syncing…</span>}
      </button>

      <div className="w-px h-5 bg-border" />

      {/* Select + Import */}
      <Button
        variant={selectionMode ? 'primary' : 'secondary'}
        size="sm"
        onClick={onToggleSelect}
      >
        {selectionMode ? (
          <><X className="w-3.5 h-3.5" />Cancel</>
        ) : (
          <><CheckSquare className="w-3.5 h-3.5" />Select</>
        )}
      </Button>
      <Button variant="primary" size="sm" onClick={onImport}>
        <Upload className="w-3.5 h-3.5" />
        Import
      </Button>
    </div>
  )
}

// ── Seed panel ────────────────────────────────────────────────────────────────

const SEED_PREVIEW = [
  { name: 'Morning Run',    sport: 'jogging',          distance: '5.2 km',  elevation: '45 m',    duration: '28 min'   },
  { name: 'Long Trail Run', sport: 'trail_running',    distance: '22.5 km', elevation: '820 m',   duration: '2h 15min' },
  { name: 'Easy Bike Ride', sport: 'touringbicycle',   distance: '12.1 km', elevation: '150 m',   duration: '45 min'   },
  { name: 'Road Century',   sport: 'road_cycling',     distance: '102 km',  elevation: '1,200 m', duration: '4h'       },
  { name: 'MTB Enduro',     sport: 'mtb_advanced',     distance: '35 km',   elevation: '1,800 m', duration: '3h 30min' },
  { name: 'E-Bike Tour',    sport: 'e_touringbicycle', distance: '80 km',   elevation: '600 m',   duration: '3h'       },
  { name: 'Alpine Hike',    sport: 'hiking',           distance: '18 km',   elevation: '1,400 m', duration: '6h'       },
  { name: 'City Walk',      sport: 'walking',          distance: '3.5 km',  elevation: '20 m',    duration: '42 min'   },
  { name: 'Ski Touring',    sport: 'skitouring',       distance: '8 km',    elevation: '900 m',   duration: '4h 30min' },
  { name: 'Pool Swim',      sport: 'swimming',         distance: '2 km',    elevation: '0 m',     duration: '45 min'   },
  { name: 'Ultra Run',      sport: 'running',          distance: '65 km',   elevation: '2,500 m', duration: '9h'       },
  { name: 'City Commute',   sport: 'citybike',         distance: '4.8 km',  elevation: '30 m',    duration: '18 min'   },
]

function SeedTab() {
  const { mutate: seed, isPending: seeding, data: seedResult, error: seedError } = useSeedActivities()
  const { mutate: clear, isPending: clearing } = useClearSeedActivities()

  return (
    <div className="space-y-4">
      <p className="text-body-sm text-text-secondary">
        Create 12 synthetic activities covering every rule condition: 10 sport types, all distance
        tiers (2 km – 102 km), all elevation bands, all duration brackets.
      </p>

      <div className="rounded-lg border border-border overflow-hidden">
        <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-4 px-4 py-2 bg-surface-raised text-caption text-text-disabled uppercase tracking-wide font-medium">
          <span>Activity</span>
          <span className="text-right">Distance</span>
          <span className="text-right">Elevation</span>
          <span className="text-right">Duration</span>
        </div>
        <div className="divide-y divide-border max-h-64 overflow-y-auto">
          {SEED_PREVIEW.map((row) => (
            <div key={row.name} className="grid grid-cols-[1fr_auto_auto_auto] gap-x-4 px-4 py-2 text-body-sm">
              <div>
                <span className="text-text-primary">{row.name}</span>
                <span className="text-text-disabled ml-2 text-caption inline-flex items-center gap-1 align-middle">
                  <SportIcon sportType={row.sport} size={14} className="opacity-70" />
                  {sportLabel(row.sport)}
                </span>
              </div>
              <span className="text-text-secondary text-right tabular-nums">{row.distance}</span>
              <span className="text-text-secondary text-right tabular-nums">{row.elevation}</span>
              <span className="text-text-secondary text-right tabular-nums">{row.duration}</span>
            </div>
          ))}
        </div>
      </div>

      {seedResult && (
        <Alert variant="success">
          <CheckCircle2 className="w-4 h-4" />
          {seedResult.created > 0
            ? `Created ${seedResult.created} test activities.`
            : `All ${seedResult.skipped_existing} test activities already exist.`}
        </Alert>
      )}
      {seedError && (
        <Alert variant="error">
          <AlertCircle className="w-4 h-4" />
          {(seedError as Error).message}
        </Alert>
      )}

      <div className="flex gap-2">
        <Button variant="primary" size="sm" loading={seeding} onClick={() => seed()}>
          <Database className="w-3.5 h-3.5" />
          Create 12 test activities
        </Button>
        <Button variant="secondary" size="sm" loading={clearing} onClick={() => clear()}>
          <Trash2 className="w-3.5 h-3.5" />
          Clear test activities
        </Button>
      </div>
    </div>
  )
}

// ── GPX client-side parsing ───────────────────────────────────────────────────

interface GpxFilePreview {
  file: File
  name: string
  /** user-editable copy of name, sent to backend on import */
  editedName: string
  sportTypeRaw: string | null
  sportTypeMapped: string | null
  distanceM: number | null
  durationS: number | null
  elevationM: number | null
  avgSpeedKmh: number | null
  maxSpeedKmh: number | null
  startedAt: Date | null
  /** true when the GPX has no trackpoint timestamps → a planned route, not a recorded activity */
  isPlanned: boolean
  /** true when a matching activity already exists in the database */
  isDuplicate: boolean
  points: { lat: number; lon: number }[]
}

/** Mirror of the backend dedup logic — returns true when the activity already exists. */
function checkDuplicate(preview: GpxFilePreview, existing: Activity[]): boolean {
  if (preview.startedAt) {
    const ms = preview.startedAt.getTime()
    return existing.some((a) => {
      if (!a.started_at) return false
      return Math.abs(new Date(a.started_at).getTime() - ms) < 2000
    })
  }
  // Planned route: match by current edited name + no started_at
  return existing.some((a) => a.started_at === null && a.activity_name === preview.editedName)
}

const GPX_SPORT_MAP: Record<string, string> = sportMappings.gpx_mapping

function mapGpxSportType(raw: string | null): string | null {
  if (!raw) return null
  const n = raw.trim().toLowerCase().replace(/[\s-]/g, '_')
  return GPX_SPORT_MAP[n] ?? n
}

function haversineM(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371000
  const φ1 = (lat1 * Math.PI) / 180, φ2 = (lat2 * Math.PI) / 180
  const Δφ = ((lat2 - lat1) * Math.PI) / 180, Δλ = ((lon2 - lon1) * Math.PI) / 180
  const a = Math.sin(Δφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) ** 2
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

// Namespace-safe child lookup — avoids querySelector issues with GPX namespace prefixes
function gpxChild(el: Element, ...path: string[]): Element | null {
  let cur: Element | null = el
  for (const tag of path) {
    if (!cur) return null
    cur = Array.from(cur.children).find((c) => c.localName === tag) ?? null
  }
  return cur
}
function gpxText(el: Element, ...path: string[]): string | null {
  return gpxChild(el, ...path)?.textContent?.trim() || null
}

async function parseGpxFile(file: File): Promise<GpxFilePreview> {
  const text = await file.text()
  const doc  = new DOMParser().parseFromString(text, 'text/xml')
  const root = doc.documentElement

  // Name priority: <trk><name>, then <metadata><name>, then filename
  const name =
    gpxText(root, 'trk', 'name') ||
    gpxText(root, 'metadata', 'name') ||
    file.name.replace(/\.gpx$/i, '')

  const sportTypeRaw    = gpxText(root, 'trk', 'type')
  const sportTypeMapped = mapGpxSportType(sportTypeRaw)

  // Collect all trackpoints with timestamps and elevation
  const pts = Array.from(doc.querySelectorAll('trkpt'))
    .map((pt) => {
      const lat = parseFloat(pt.getAttribute('lat') ?? '')
      const lon = parseFloat(pt.getAttribute('lon') ?? '')
      const eleEl = Array.from(pt.children).find((c) => c.localName === 'ele')
      const timeEl = Array.from(pt.children).find((c) => c.localName === 'time')
      const ele = parseFloat(eleEl?.textContent ?? '0') || 0
      const ts  = timeEl?.textContent
      const t   = ts ? new Date(ts) : null
      return { lat, lon, ele, time: t && !isNaN(t.getTime()) ? t : null }
    })
    .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon) && (p.lat !== 0 || p.lon !== 0))

  // Distance via Haversine
  let distanceM = 0
  for (let i = 1; i < pts.length; i++)
    distanceM += haversineM(pts[i - 1].lat, pts[i - 1].lon, pts[i].lat, pts[i].lon)

  // Elevation gain (sum of positive differences)
  let elevationM = 0
  for (let i = 1; i < pts.length; i++) {
    const d = pts[i].ele - pts[i - 1].ele
    if (d > 0) elevationM += d
  }

  // Time information
  const times     = pts.map((p) => p.time).filter((t): t is Date => t !== null)
  const isPlanned = times.length === 0
  const startedAt = times.length > 0 ? times[0] : null
  const durationS =
    times.length > 1 ? (times[times.length - 1].getTime() - times[0].getTime()) / 1000 : null

  // Speed stats (only when timestamps are present)
  const finalDistM = distanceM > 0 ? distanceM : null
  const avgSpeedKmh =
    finalDistM != null && durationS != null && durationS > 0
      ? (finalDistM / 1000) / (durationS / 3600)
      : null

  let maxSpeedKmh: number | null = null
  if (times.length >= 2) {
    let maxMs = 0
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i]
      if (!a.time || !b.time) continue
      const dt = (b.time.getTime() - a.time.getTime()) / 1000
      if (dt <= 0) continue
      const ms = haversineM(a.lat, a.lon, b.lat, b.lon) / dt
      // Cap at 150 km/h to filter GPS noise spikes
      if (ms < 41.67 && ms > maxMs) maxMs = ms
    }
    maxSpeedKmh = maxMs > 0 ? maxMs * 3.6 : null
  }

  return {
    file,
    name,
    editedName: name,
    sportTypeRaw,
    sportTypeMapped,
    distanceM:    finalDistM,
    durationS,
    elevationM:   elevationM > 1 ? elevationM : null,
    avgSpeedKmh,
    maxSpeedKmh,
    startedAt,
    isPlanned,
    isDuplicate: false,   // stamped after parsing, once existing activities are known
    points: pts.map((p) => ({ lat: p.lat, lon: p.lon })),
  }
}

// ── GPX preview card ──────────────────────────────────────────────────────────

function GpxPreviewCard({
  preview,
  onRemove,
  onNameChange,
}: {
  preview: GpxFilePreview
  onRemove: () => void
  onNameChange: (name: string) => void
}) {
  const [showMap, setShowMap] = useState(true)
  const [editingName, setEditingName] = useState(false)
  const nameInputRef = useRef<HTMLInputElement>(null)
  const sport = preview.sportTypeMapped

  function commitName(val: string) {
    setEditingName(false)
    onNameChange(val.trim() || preview.name)
  }

  // Build stats list once so both sections can reference it
  const previewStats: { label: string; value: string; icon: React.ReactNode }[] = [
    ...(preview.distanceM  != null ? [{ label: 'Distance',  icon: <Ruler className="w-3.5 h-3.5" />,      value: formatDistance(preview.distanceM) }] : []),
    ...(preview.durationS  != null ? [{ label: 'Duration',  icon: <Clock className="w-3.5 h-3.5" />,      value: formatDuration(preview.durationS) }] : []),
    ...(preview.elevationM != null ? [{ label: 'Elevation', icon: <TrendingUp className="w-3.5 h-3.5" />, value: `${Math.round(preview.elevationM)} m` }] : []),
    ...(preview.avgSpeedKmh != null ? [{ label: 'Avg speed', icon: <Gauge className="w-3.5 h-3.5" />,    value: `${preview.avgSpeedKmh.toFixed(1)} km/h` }] : []),
    ...(preview.maxSpeedKmh != null ? [{ label: 'Max speed', icon: <Zap className="w-3.5 h-3.5" />,      value: `${preview.maxSpeedKmh.toFixed(1)} km/h` }] : []),
  ]
  const statCols = previewStats.length <= 3 ? 'grid-cols-3' : previewStats.length === 4 ? 'grid-cols-4' : 'grid-cols-5'

  return (
    <div className={`rounded-xl border overflow-hidden ${preview.isDuplicate ? 'border-warning/50 opacity-75' : 'border-border'}`}>

      {/* Duplicate warning */}
      {preview.isDuplicate && (
        <div className="flex items-center gap-2 px-4 py-2 bg-warning/10 border-b border-warning/20">
          <AlertCircle className="w-3.5 h-3.5 text-warning flex-shrink-0" />
          <span className="text-caption text-warning">Already imported — will be skipped</span>
        </div>
      )}

      {/* ── Map — isolated stacking context so Leaflet z-indexes don't leak out ── */}
      {showMap && preview.points.length > 1 && (
        <div className="relative isolate" style={{ height: 180 }}>
          <ActivityMap points={preview.points} />
        </div>
      )}

      {/* ── Header: name / badge / sport / actions ── */}
      <div className="relative z-10 flex items-start justify-between gap-3 px-4 pt-3 pb-2 bg-surface-raised">
        <div className="min-w-0 flex-1">
          {/* Editable name + type badge */}
          <div className="flex items-center gap-2 flex-wrap">
            {editingName ? (
              <input
                ref={nameInputRef}
                defaultValue={preview.editedName}
                autoFocus
                className="text-body-sm font-semibold text-text-primary bg-surface border border-primary/60 rounded px-1.5 py-0.5 outline-none min-w-0 flex-1"
                onBlur={(e) => commitName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitName((e.target as HTMLInputElement).value)
                  if (e.key === 'Escape') setEditingName(false)
                }}
              />
            ) : (
              <span className="flex items-center gap-1.5 min-w-0">
                <span className="text-body-sm font-semibold text-text-primary truncate">{preview.editedName}</span>
                <button
                  onClick={() => setEditingName(true)}
                  title="Rename"
                  className="flex-shrink-0 p-0.5 rounded text-text-disabled hover:text-primary hover:bg-primary/10 transition-colors"
                >
                  <svg className="w-3 h-3" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M11.5 2.5a1.5 1.5 0 0 1 2.12 2.12L5 13.25l-2.75.5.5-2.75L11.5 2.5z" strokeLinejoin="round" />
                  </svg>
                </button>
              </span>
            )}
            <Badge variant={preview.isPlanned ? 'neutral' : 'connected'}>
              {preview.isPlanned ? 'Planned route' : 'Recorded'}
            </Badge>
          </div>

          {/* Sport type */}
          {sport && (
            <p className="flex items-center gap-1 text-caption text-text-secondary mt-1">
              <SportIcon sportType={sport} size={11} className="opacity-70 flex-shrink-0" />
              {sportLabel(sport)}
            </p>
          )}
        </div>

        {/* Map toggle + remove */}
        <div className="flex items-center gap-0.5 flex-shrink-0">
          {preview.points.length > 1 && (
            <button
              onClick={() => setShowMap((v) => !v)}
              className="px-2 py-1 rounded-md text-caption text-text-disabled hover:text-text-secondary hover:bg-surface transition-colors"
            >
              {showMap ? 'Hide map' : 'Map'}
            </button>
          )}
          <button
            onClick={onRemove}
            className="p-1.5 rounded-md text-text-disabled hover:text-error hover:bg-error/10 transition-colors"
            title="Remove"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* ── Stats grid ── */}
      {previewStats.length > 0 ? (
        <div className={`relative z-10 grid ${statCols} gap-px bg-border border-t border-border`}>
          {previewStats.map(({ label, value, icon }) => (
            <div key={label} className="bg-surface-raised flex flex-col items-center gap-1 py-2.5 px-2 text-center">
              <span className="text-text-disabled">{icon}</span>
              <p className="text-body-sm font-semibold text-text-primary tabular-nums leading-none">{value}</p>
              <p className="text-[9px] font-medium text-text-disabled uppercase tracking-wider leading-none">{label}</p>
            </div>
          ))}
        </div>
      ) : preview.isPlanned ? (
        <p className="px-4 py-2 text-caption text-text-disabled italic border-t border-border bg-surface-raised">No timestamps — planned route</p>
      ) : null}

    </div>
  )
}

// ── GPX upload tab ────────────────────────────────────────────────────────────

function GpxTab({ onClose }: { onClose: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const { mutate: importGpx, isPending, data: importResult, error: importError, reset } = useImportGpx()
  const [dragOver, setDragOver] = useState(false)
  const [previews, setPreviews] = useState<GpxFilePreview[]>([])
  const [parsing, setParsing]   = useState(false)

  // Use the same activities hook the main page uses — already cached by React Query,
  // correct auth, and available synchronously on re-opens of the dialog.
  const { data: existingData, isLoading: loadingExisting } = useActivities({
    limit: 500,
    filters: { source: 'import' },
  })
  const existingImports: Activity[] = useMemo(() => existingData?.data ?? [], [existingData])

  // Keep a ref so handleFiles can always read the latest list without being
  // recreated every time the query refreshes.
  const existingImportsRef = useRef<Activity[]>([])
  existingImportsRef.current = existingImports

  // Re-stamp all staged previews whenever the existing-imports list refreshes
  useEffect(() => {
    if (loadingExisting) return
    setPreviews((prev) =>
      prev.map((p) => ({ ...p, isDuplicate: checkDuplicate(p, existingImportsRef.current) }))
    )
  }, [existingImports, loadingExisting]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleFiles = useCallback(async (files: FileList | null) => {
    if (!files) return
    const gpxFiles = Array.from(files).filter((f) => f.name.toLowerCase().endsWith('.gpx'))
    if (gpxFiles.length === 0) return
    setParsing(true)
    reset()
    const parsed = await Promise.all(gpxFiles.map(parseGpxFile))
    const stamped = parsed.map((p) => ({ ...p, isDuplicate: checkDuplicate(p, existingImportsRef.current) }))
    setPreviews((prev) => {
      const stagedNames = new Set(prev.map((p) => p.file.name))
      return [...prev, ...stamped.filter((p) => !stagedNames.has(p.file.name))]
    })
    setParsing(false)
  }, [reset])

  const removeFile = (idx: number) => {
    setPreviews((prev) => prev.filter((_, i) => i !== idx))
    reset()
  }

  // Re-run duplicate check when the user edits the name (planned routes dedup by name)
  const updateName = (idx: number, name: string) => {
    setPreviews((prev) => prev.map((p, i) => {
      if (i !== idx) return p
      const updated = { ...p, editedName: name }
      return { ...updated, isDuplicate: checkDuplicate(updated, existingImportsRef.current) }
    }))
  }

  // Auto-close after full success (no errors)
  useEffect(() => {
    if (importResult && importResult.errors.length === 0) {
      const t = setTimeout(onClose, 1200)
      return () => clearTimeout(t)
    }
  }, [importResult, onClose])

  const hasFiles = previews.length > 0
  const checkingDuplicates = loadingExisting && hasFiles

  return (
    <div className="space-y-4">
      {/* Drop zone — compact once files are staged */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); void handleFiles(e.dataTransfer.files) }}
        onClick={() => fileRef.current?.click()}
        className={`flex items-center justify-center gap-3 rounded-lg border-2 border-dashed cursor-pointer transition-all ${
          hasFiles ? 'py-3' : 'flex-col py-10'
        } ${dragOver ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50 hover:bg-surface-raised'}`}
      >
        {parsing ? (
          <Loader2 className="w-5 h-5 animate-spin text-text-disabled" />
        ) : (
          <Upload className={`${hasFiles ? 'w-4 h-4' : 'w-8 h-8'} ${dragOver ? 'text-primary' : 'text-text-disabled'}`} />
        )}
        {hasFiles ? (
          <p className="text-body-sm text-text-secondary">
            {parsing ? 'Parsing…' : 'Drop more files or click to browse'}
          </p>
        ) : (
          <div className="text-center">
            <p className="text-body-sm text-text-primary">
              {parsing ? 'Parsing files…' : 'Drop GPX files here or click to browse'}
            </p>
            <p className="text-caption text-text-disabled mt-0.5">Recorded activities and planned routes</p>
          </div>
        )}
        <input ref={fileRef} type="file" accept=".gpx" multiple className="sr-only"
          onChange={(e) => { void handleFiles(e.target.files) }} />
      </div>

      {/* Per-file preview cards */}
      {previews.map((p, idx) => (
        <GpxPreviewCard
          key={`${p.file.name}-${idx}`}
          preview={p}
          onRemove={() => removeFile(idx)}
          onNameChange={(name) => updateName(idx, name)}
        />
      ))}

      {checkingDuplicates && (
        <p className="flex items-center gap-1.5 text-caption text-text-disabled">
          <Loader2 className="w-3 h-3 animate-spin" />
          Checking for duplicates…
        </p>
      )}

      {/* Import result */}
      {importResult && (
        <div className="space-y-2">
          {importResult.created.length > 0 && (
            <Alert variant="success">
              <CheckCircle2 className="w-4 h-4" />
              Imported {importResult.created.length} {importResult.created.length === 1 ? 'activity' : 'activities'}.
              {importResult.errors.length === 0 && ' Closing…'}
            </Alert>
          )}
          {importResult.errors.length > 0 && (
            <Alert variant="error">
              <AlertCircle className="w-4 h-4" />
              {importResult.errors.map((e) => `${e.file}: ${e.error}`).join(' · ')}
            </Alert>
          )}
        </div>
      )}
      {importError && (
        <Alert variant="error">
          <AlertCircle className="w-4 h-4" />
          {(importError as Error).message}
        </Alert>
      )}

      {/* Import button — only while importable files are staged */}
      {(() => {
        const importable = previews.filter((p) => !p.isDuplicate)
        if (!hasFiles || importResult) return null
        return (
          <Button
            variant="primary"
            size="sm"
            loading={isPending}
            disabled={importable.length === 0}
            onClick={() => importGpx({ files: importable.map((p) => p.file), names: importable.map((p) => p.editedName) })}
          >
            <Upload className="w-3.5 h-3.5" />
            Import {importable.length} {importable.length === 1 ? 'file' : 'files'}
            {importable.length < previews.length && (
              <span className="opacity-60 font-normal">
                ({previews.length - importable.length} duplicate{previews.length - importable.length > 1 ? 's' : ''} skipped)
              </span>
            )}
          </Button>
        )
      })()}
    </div>
  )
}

// ── Import panel ──────────────────────────────────────────────────────────────

type ImportTab = 'seed' | 'gpx'

function ImportPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<ImportTab>('gpx')

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/50"
      onClick={onClose}>
      <div className="w-full max-w-xl bg-bg border border-border rounded-xl shadow-xl animate-in fade-in slide-in-from-bottom-4"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="text-heading-sm text-text-primary font-semibold">Import activities</h2>
          <button onClick={onClose} className="p-1.5 rounded-md hover:bg-surface-raised text-text-secondary hover:text-text-primary transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex border-b border-border px-6">
          {(['gpx', 'seed'] as ImportTab[]).map((key) => (
            <button key={key} onClick={() => setTab(key)}
              className={`px-4 py-2.5 text-body-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === key ? 'border-primary text-primary' : 'border-transparent text-text-secondary hover:text-text-primary'
              }`}>
              {key === 'gpx' ? 'Upload GPX' : 'Seed test data'}
            </button>
          ))}
        </div>
        <div className="px-6 py-5">{tab === 'gpx' ? <GpxTab onClose={onClose} /> : <SeedTab />}</div>
      </div>
    </div>
  )
}

// ── Sync destination tile ─────────────────────────────────────────────────────

function SyncTile({
  platform,
  present,
  href,
  loading,
  onSync,
}: {
  platform: PlatformKey
  present: boolean
  href?: string | null
  loading: boolean
  onSync: () => void
}) {
  const brand = getBrand(platform)

  if (present) {
    return (
      <a
        href={href ?? '#'}
        target={href ? '_blank' : undefined}
        rel="noopener noreferrer"
        className="group flex items-center gap-3 px-3 py-2.5 rounded-xl border border-border bg-surface-raised hover:border-[var(--brand)] transition-all"
        style={{ '--brand': `${brand.colors.primary}60` } as React.CSSProperties}
        title={href ? `View on ${brand.name}` : `On ${brand.name}`}
      >
        <div
          className="flex items-center justify-center w-7 h-7 rounded-lg flex-shrink-0"
          style={{ backgroundColor: `${brand.colors.primary}20` }}
        >
          <BrandIcon brand={platform} size={14} variant="regular" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-caption font-medium text-text-primary truncate">{brand.name}</p>
          <p className="text-[10px] text-text-disabled">Synced</p>
        </div>
        <CheckCircle2 className="w-4 h-4 flex-shrink-0" style={{ color: brand.colors.primary }} />
      </a>
    )
  }

  return (
    <button
      onClick={onSync}
      disabled={loading}
      className="group flex items-center gap-3 px-3 py-2.5 rounded-xl border border-border bg-surface hover:border-[var(--brand)] hover:bg-[var(--brand-bg)] transition-all disabled:opacity-50"
      style={{
        '--brand':    `${brand.colors.primary}60`,
        '--brand-bg': `${brand.colors.primary}08`,
      } as React.CSSProperties}
    >
      <div
        className="flex items-center justify-center w-7 h-7 rounded-lg flex-shrink-0 opacity-60 group-hover:opacity-100 transition-opacity"
        style={{ backgroundColor: `${brand.colors.primary}15` }}
      >
        {loading ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" style={{ color: brand.colors.primary }} />
        ) : (
          <BrandIcon brand={platform} size={14} variant="regular" />
        )}
      </div>
      <div className="flex-1 min-w-0 text-left">
        <p className="text-caption font-medium text-text-secondary group-hover:text-text-primary truncate transition-colors">{brand.name}</p>
        <p className="text-[10px] text-text-disabled">Click to sync</p>
      </div>
    </button>
  )
}

// ── Activity detail panel ─────────────────────────────────────────────────────

function ActivityDetail({
  act,
  connectedPlatforms,
  onClose,
}: {
  act: Activity
  connectedPlatforms: PlatformKey[]
  onClose: () => void
}) {
  const { mutate: syncActivity, isPending: syncing, variables: syncVars, data: syncResult } = useSyncActivity()
  const { mutate: deleteActivity, isPending: deleting } = useDeleteActivity()
  const isImported  = act.source === 'import'
  const isPlanned   = isImported && act.started_at === null
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleteResult, setDeleteResult] = useState<{ deleted_from: string[]; failed: { platform: string; reason: string }[] } | null>(null)

  const platformsToDelete = connectedPlatforms.filter((p) => activityOnPlatform(act, p))

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const handleDelete = () => {
    deleteActivity(act.id, {
      onSuccess: (result: unknown) => {
        const r = result as { deleted_from: string[]; failed: { platform: string; reason: string }[] }
        setDeleteResult(r)
        setConfirmDelete(false)
        setTimeout(() => onClose(), 1500)
      },
    })
  }

  const [mapPoints, setMapPoints] = useState<{ lat: number; lon: number }[]>([])
  const [mapLoading, setMapLoading] = useState(false)
  const [maxSpeedKmh, setMaxSpeedKmh] = useState<number | null>(null)

  useEffect(() => {
    if (!act.has_gpx) return
    const token = useAuthStore.getState().token
    setMapLoading(true)
    fetch(`/api/v1/activities/${act.id}/gpx`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: 'include',
    })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`${r.status}`))))
      .then((text) => {
        setMapPoints(parseGpxPoints(text))
        // Compute max speed from timestamped trackpoints
        const doc  = new DOMParser().parseFromString(text, 'application/xml')
        const tpts = Array.from(doc.querySelectorAll('trkpt')).map((pt) => {
          const lat = parseFloat(pt.getAttribute('lat') ?? '')
          const lon = parseFloat(pt.getAttribute('lon') ?? '')
          const tEl = Array.from(pt.children).find((c) => c.localName === 'time')
          const t   = tEl?.textContent ? new Date(tEl.textContent) : null
          return { lat, lon, time: t && !isNaN(t.getTime()) ? t : null }
        }).filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon))

        let maxMs = 0
        for (let i = 1; i < tpts.length; i++) {
          const a = tpts[i - 1], b = tpts[i]
          if (!a.time || !b.time) continue
          const dt  = (b.time.getTime() - a.time.getTime()) / 1000
          if (dt <= 0) continue
          const R   = 6371000
          const φ1  = (a.lat * Math.PI) / 180, φ2 = (b.lat * Math.PI) / 180
          const Δφ  = ((b.lat - a.lat) * Math.PI) / 180
          const Δλ  = ((b.lon - a.lon) * Math.PI) / 180
          const hav = Math.sin(Δφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) ** 2
          const ms  = 2 * R * Math.atan2(Math.sqrt(hav), Math.sqrt(1 - hav)) / dt
          if (ms < 41.67 && ms > maxMs) maxMs = ms   // cap at 150 km/h
        }
        setMaxSpeedKmh(maxMs > 0 ? maxMs * 3.6 : null)
      })
      .catch(() => { setMapPoints([]); setMaxSpeedKmh(null) })
      .finally(() => setMapLoading(false))
  }, [act.id, act.has_gpx])

  // Avg speed from stored distance + duration
  const avgSpeedKmh =
    act.distance_m != null && act.duration_seconds != null && act.duration_seconds > 0
      ? (act.distance_m / 1000) / (act.duration_seconds / 3600)
      : null

  // Which platforms can still be synced (not present yet but user is connected)
  const syncablePlatforms = connectedPlatforms.filter((p) => !activityOnPlatform(act, p))
  const presentPlatforms  = connectedPlatforms.filter((p) => activityOnPlatform(act, p))

  function getPlatformHref(platform: PlatformKey): string | null {
    if (platform === 'komoot' && act.komoot_tour_id) return `https://www.komoot.com/tour/${act.komoot_tour_id}`
    if (platform === 'strava' && act.strava_activity_id) return `https://www.strava.com/activities/${act.strava_activity_id}`
    return null
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/50"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg bg-bg border border-border rounded-xl shadow-xl animate-in fade-in slide-in-from-bottom-4 overflow-y-auto max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4 px-6 pt-5 pb-4 border-b border-border">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-heading-sm text-text-primary font-semibold leading-tight">
                {act.activity_name ?? 'Untitled activity'}
              </h2>
              {isPlanned ? (
                <Badge variant="neutral">Planned route</Badge>
              ) : isImported ? (
                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-border bg-surface text-[10px] font-medium uppercase tracking-wider text-text-secondary">
                  <BrandIcon brand="local" size={10} variant="regular" />
                  Local
                </span>
              ) : null}
            </div>
            <p className="flex items-center gap-1.5 text-body-sm text-text-secondary mt-0.5">
              <SportIcon sportType={act.sport_type ?? ''} size={15} className="opacity-70 flex-shrink-0" />
              {act.sport_type ? sportLabel(act.sport_type) : 'Activity'}
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 p-1.5 rounded-md hover:bg-surface-raised text-text-secondary hover:text-text-primary transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Map — isolate so Leaflet z-indexes don't bleed into stats below */}
        {act.has_gpx && (
          <div className="relative isolate px-6 pt-4 pb-2">
            {mapLoading ? (
              <div className="flex items-center justify-center h-[220px] rounded-xl border border-border bg-surface-raised">
                <Loader2 className="w-5 h-5 animate-spin text-text-disabled" />
              </div>
            ) : mapPoints.length > 0 ? (
              <ActivityMap points={mapPoints} />
            ) : null}
          </div>
        )}

        {/* Stats */}
        {(() => {
          const stats: { label: string; value: string; icon: React.ReactNode }[] = [
            { label: 'Distance',  icon: <Ruler className="w-4 h-4" />,      value: act.distance_m != null      ? formatDistance(act.distance_m)        : '—' },
            { label: 'Duration',  icon: <Clock className="w-4 h-4" />,      value: act.duration_seconds != null ? formatDuration(act.duration_seconds)  : '—' },
            { label: 'Elevation', icon: <TrendingUp className="w-4 h-4" />, value: act.elevation_up_m != null   ? `${Math.round(act.elevation_up_m)} m` : '—' },
            ...(avgSpeedKmh != null ? [{ label: 'Avg speed', icon: <Gauge className="w-4 h-4" />, value: `${avgSpeedKmh.toFixed(1)} km/h` }] : []),
            ...(maxSpeedKmh != null ? [{ label: 'Max speed', icon: <Zap className="w-4 h-4" />,   value: `${maxSpeedKmh.toFixed(1)} km/h` }] : []),
          ]
          const colClass = stats.length <= 3 ? 'grid-cols-3' : stats.length === 4 ? 'grid-cols-4' : 'grid-cols-5'
          return (
            <div className={`grid ${colClass} gap-px bg-border mx-6 my-4 rounded-xl overflow-hidden`}>
              {stats.map(({ label, value, icon }) => (
                <div key={label} className="bg-surface-raised px-2 py-3 flex flex-col items-center gap-1.5 text-center">
                  <span className="text-text-disabled">{icon}</span>
                  <p className="text-heading-sm text-text-primary font-semibold tabular-nums leading-none text-center w-full">{value}</p>
                  <p className="text-[9px] font-medium text-text-disabled uppercase tracking-wider leading-none text-center w-full">{label}</p>
                </div>
              ))}
            </div>
          )
        })()}

        {/* Detailed track analysis — profile panels, zones, splits */}
        {act.has_gpx && <ActivityAnalysis activityId={act.id} />}

        {/* Body */}
        <div className="px-6 pb-4 space-y-5">
          {/* Timestamps */}
          <div className="flex items-center gap-4 text-caption text-text-disabled">
            {act.started_at && (
              <span className="flex items-center gap-1.5">
                <Clock className="w-3 h-3" />
                {formatRelative(new Date(act.started_at))}
              </span>
            )}
            <span className="flex items-center gap-1.5">
              <ArrowRight className="w-3 h-3" />
              Recorded {formatRelative(new Date(act.synced_at))}
            </span>
          </div>

          {/* Sync section — only shown if user has any connections */}
          {connectedPlatforms.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <p className="text-label text-text-disabled uppercase tracking-wider">Connections</p>
                {isPlanned && (
                  <span className="text-caption text-text-disabled italic">Planned route — no timestamps</span>
                )}
              </div>
              {isPlanned && syncablePlatforms.length > 0 && (
                <div className="flex items-start gap-2 px-3 py-2.5 bg-warning/10 border border-warning/20 rounded-lg mb-3">
                  <AlertCircle className="w-3.5 h-3.5 text-warning flex-shrink-0 mt-0.5" />
                  <p className="text-caption text-warning">
                    This is a planned route (no timestamps). Platforms may import it as a route rather than a completed activity.
                  </p>
                </div>
              )}
              <div className="grid grid-cols-2 gap-2">
                {presentPlatforms.map((p) => (
                  <SyncTile
                    key={p}
                    platform={p}
                    present
                    href={getPlatformHref(p)}
                    loading={false}
                    onSync={() => {}}
                  />
                ))}
                {syncablePlatforms.map((p) => (
                  <SyncTile
                    key={p}
                    platform={p}
                    present={false}
                    href={null}
                    loading={syncing && (syncVars as { id: string; destination?: string } | undefined)?.destination === p}
                    onSync={() => syncActivity({ id: act.id, destination: p })}
                  />
                ))}
              </div>
              {syncablePlatforms.length > 1 && (
                <Button
                  variant="secondary"
                  size="sm"
                  className="mt-3 w-full"
                  loading={syncing}
                  onClick={() => syncActivity({ id: act.id, destination: syncablePlatforms[0] })}
                >
                  Sync to all {syncablePlatforms.length} platforms
                </Button>
              )}
            </div>
          )}

          {/* Error */}
          {act.sync_status === 'failed' && act.conflict_reason && (
            <div className="flex items-start gap-2 px-3 py-2.5 bg-error/10 border border-error/20 rounded-lg">
              <AlertCircle className="w-4 h-4 text-error flex-shrink-0 mt-0.5" />
              <p className="text-caption text-error">{act.conflict_reason}</p>
            </div>
          )}

          {syncResult && (
            <div className="flex items-start gap-2 px-3 py-2.5 bg-success/10 border border-success/20 rounded-lg">
              <CheckCircle2 className="w-4 h-4 text-success flex-shrink-0 mt-0.5" />
              <p className="text-caption text-success">{syncResult.message}</p>
            </div>
          )}

          {deleteResult && (
            <div className="flex items-start gap-2 px-3 py-2.5 bg-success/10 border border-success/20 rounded-lg">
              <CheckCircle2 className="w-4 h-4 text-success flex-shrink-0 mt-0.5" />
              <p className="text-caption text-success">
                Deleted
                {deleteResult.deleted_from.length > 0
                  ? ` from ${deleteResult.deleted_from.join(' & ')}`
                  : ' locally'}
                .
              </p>
            </div>
          )}

          {/* Delete confirmation */}
          {confirmDelete && (
            <div className="flex flex-col gap-3 px-4 py-3 bg-error/10 rounded-xl border border-error/30">
              <p className="text-caption text-text-primary font-medium">
                Permanently delete this activity
                {platformsToDelete.length > 0
                  ? ` and remove it from ${platformsToDelete.map((p) => getBrand(p).name).join(' & ')}`
                  : ''}?
              </p>
              <div className="flex items-center gap-2">
                <Button variant="primary" size="sm" loading={deleting} onClick={handleDelete}
                  className="bg-error hover:bg-error/90 border-error">
                  <Trash2 className="w-3.5 h-3.5" />
                  Delete everywhere
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-2 px-6 pb-5 pt-3 border-t border-border">
          {!confirmDelete && !deleteResult && (
            <Button variant="ghost" size="sm" loading={deleting}
              onClick={() => setConfirmDelete(true)}
              className="text-error hover:text-error">
              <Trash2 className="w-3.5 h-3.5" />
              Delete
            </Button>
          )}
          <div className="flex-1" />
          <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
        </div>
      </div>
    </div>
  )
}

// ── Bulk action bar ───────────────────────────────────────────────────────────

function BulkActionBar({
  count,
  connectedPlatforms,
  loading,
  onSync,
  onCancel,
}: {
  count: number
  connectedPlatforms: PlatformKey[]
  loading: boolean
  onSync: (dest: PlatformKey) => void
  onCancel: () => void
}) {
  if (count === 0) return null
  return (
    <div className="fixed bottom-[68px] md:bottom-6 left-1/2 -translate-x-1/2 z-40
      flex items-center gap-2 px-4 py-3 bg-surface border border-border-strong rounded-xl shadow-xl
      animate-in slide-in-from-bottom-2 whitespace-nowrap max-w-[calc(100vw-2rem)] overflow-x-auto">
      <span className="text-body-sm text-text-primary font-medium flex-shrink-0">
        {count} selected
      </span>
      <div className="w-px h-4 bg-border flex-shrink-0" />
      {connectedPlatforms.length > 0 ? (
        connectedPlatforms.map((p) => {
          const brand = getBrand(p)
          return (
            <button
              key={p}
              disabled={loading}
              onClick={() => onSync(p)}
              className="flex items-center gap-1.5 h-8 px-3 rounded-lg text-white text-body-sm font-medium transition-opacity hover:opacity-90 disabled:opacity-50 flex-shrink-0"
              style={{ backgroundColor: brand.colors.primary }}
            >
              {loading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <BrandIcon brand={p} size={13} variant="white" />
              )}
              {brand.name}
            </button>
          )
        })
      ) : (
        <span className="text-caption text-text-disabled">No connections configured</span>
      )}
      <div className="w-px h-4 bg-border flex-shrink-0" />
      <Button variant="ghost" size="sm" onClick={onCancel} className="flex-shrink-0">Cancel</Button>
    </div>
  )
}

// ── Activity row ──────────────────────────────────────────────────────────────

function ActivityRow({
  act,
  connectedPlatforms,
  onClick,
  selectionMode,
  selected,
  onToggle,
}: {
  act: Activity
  connectedPlatforms: PlatformKey[]
  onClick: () => void
  selectionMode: boolean
  selected: boolean
  onToggle: () => void
}) {
  const isFailed     = act.sync_status === 'failed'
  const isProcessing = act.sync_status === 'processing'
  const isPlanned    = act.source === 'import' && act.started_at === null

  return (
    <div className={`flex items-center border-b border-border last:border-b-0 hover:bg-surface-raised/60 transition-colors ${selected ? 'bg-primary/5' : ''}`}>
      {selectionMode && (
        <label className="flex-shrink-0 pl-4 pr-2 py-3 flex items-center cursor-pointer" onClick={(e) => e.stopPropagation()}>
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            className="w-4 h-4 rounded border-border accent-primary cursor-pointer"
          />
        </label>
      )}
      <button
        onClick={selectionMode ? onToggle : onClick}
        className="flex-1 flex items-center gap-4 px-6 py-3 text-left min-w-0"
      >
        {/* Platform strip */}
        <PlatformStrip act={act} connectedPlatforms={connectedPlatforms} />

        {/* Name + meta */}
        <div className="flex-1 min-w-0">
          <p className="text-body text-text-primary truncate leading-snug">
            {act.activity_name ?? 'Untitled activity'}
          </p>
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            <span className="flex items-center gap-1.5 text-caption text-text-secondary">
              <SportIcon sportType={act.sport_type ?? ''} size={14} className="opacity-70 flex-shrink-0" />
              {act.sport_type ? sportLabel(act.sport_type) : 'Activity'}
            </span>
            {act.distance_m != null && (
              <span className="text-caption text-text-disabled tabular-nums">{formatDistance(act.distance_m)}</span>
            )}
            {act.duration_seconds != null && (
              <span className="text-caption text-text-disabled tabular-nums">{formatDuration(act.duration_seconds)}</span>
            )}
          </div>
          {isFailed && act.conflict_reason && (
            <p className="text-caption text-error mt-0.5 truncate">{act.conflict_reason}</p>
          )}
        </div>

        {/* Status + date */}
        <div className="flex-shrink-0 flex flex-col items-end gap-1">
          {isPlanned && !isFailed && !isProcessing && (
            <Badge variant="neutral">Route</Badge>
          )}
          {isFailed && (
            <Badge variant="error">
              <AlertCircle className="w-3 h-3" />
              Failed
            </Badge>
          )}
          {isProcessing && (
            <Badge variant="pending">
              <Loader2 className="w-3 h-3 animate-spin" />
              Syncing
            </Badge>
          )}
          <p className="text-caption text-text-disabled tabular-nums">
            {act.started_at
              ? new Date(act.started_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
              : formatRelative(new Date(act.synced_at))}
          </p>
        </div>
      </button>
    </div>
  )
}

// ── Group header ──────────────────────────────────────────────────────────────

function GroupHeader({ label, count }: { label: string; count: number }) {
  return (
    <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-2 bg-surface-raised/95 backdrop-blur-sm border-b border-border">
      <span className="text-label text-text-secondary font-semibold uppercase tracking-wider">{label}</span>
      <span className="text-caption text-text-disabled">{count}</span>
    </div>
  )
}

// ── Sort + Group helpers ──────────────────────────────────────────────────────

function sortActivities(activities: Activity[], sort: SortConfig): Activity[] {
  return [...activities].sort((a, b) => {
    let cmp = 0
    switch (sort.field) {
      case 'date':
        cmp = new Date(a.started_at ?? a.synced_at).getTime() - new Date(b.started_at ?? b.synced_at).getTime()
        break
      case 'distance':
        cmp = (a.distance_m ?? 0) - (b.distance_m ?? 0)
        break
      case 'duration':
        cmp = (a.duration_seconds ?? 0) - (b.duration_seconds ?? 0)
        break
      case 'elevation':
        cmp = (a.elevation_up_m ?? 0) - (b.elevation_up_m ?? 0)
        break
      case 'name':
        cmp = (a.activity_name ?? '').localeCompare(b.activity_name ?? '')
        break
    }
    return sort.dir === 'asc' ? cmp : -cmp
  })
}

function groupActivities(activities: Activity[], groupBy: GroupBy): { key: string; label: string; items: Activity[] }[] {
  if (groupBy === 'none') return [{ key: 'all', label: '', items: activities }]

  const groups = new Map<string, { label: string; items: Activity[] }>()

  for (const act of activities) {
    let key: string
    let label: string

    if (groupBy === 'month') {
      const d = new Date(act.started_at ?? act.synced_at)
      key   = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
      label = d.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
    } else if (groupBy === 'sport') {
      key   = act.sport_type ?? 'unknown'
      label = sportLabel(act.sport_type ?? '')
    } else {
      // source
      key   = act.source
      label = act.source === 'import' ? 'Local / GPX' : (PLATFORM_LABELS as Record<string, string>)[act.source] ?? act.source
    }

    if (!groups.has(key)) groups.set(key, { label, items: [] })
    groups.get(key)!.items.push(act)
  }

  return Array.from(groups.entries())
    .map(([key, { label, items }]) => ({ key, label, items }))
    .sort((a, b) => a.key.localeCompare(b.key))
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ActivitiesPage() {
  const user               = useAuthStore((s) => s.user)
  const connectedPlatforms = useMemo(() => getConnectedPlatforms(user as UserMe | null), [user])

  // ── Sync trigger ─────────────────────────────────────────────────────────────
  const { mutate: triggerSync, isPending: isSyncing } = useTriggerSync()
  const { data: syncStatus } = useSyncStatus()
  // Fire one background sync on mount so the list is fresh.
  // useRef guard prevents re-firing on Strict Mode's simulated remount.
  // isSyncing uses the mutation's own isPending — no separate state needed,
  // which avoids the React Query v5 issue where per-mutate onSettled callbacks
  // are suppressed when the component unmounts before the response arrives.
  const triggeredRef = useRef(false)
  useEffect(() => {
    if (triggeredRef.current) return
    triggeredRef.current = true
    triggerSync()
  }, [triggerSync])

  const handleManualRefresh = useCallback(() => {
    triggerSync()
  }, [triggerSync])

  // ── Pagination ────────────────────────────────────────────────────────────────
  const [skip, setSkip] = useState(0)

  // ── Filters ───────────────────────────────────────────────────────────────────
  const [filters, setFilters]         = useState<ActivityFilters>({})
  const [searchInput, setSearchInput] = useState('')
  const [datePreset, setDatePreset]   = useState<DatePreset>('all')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const applyFilter = useCallback((patch: Partial<ActivityFilters>) => {
    setFilters((prev) => {
      const next = { ...prev, ...patch }
      Object.keys(next).forEach(
        (k) => next[k as keyof ActivityFilters] === undefined && delete next[k as keyof ActivityFilters],
      )
      return next
    })
    setSkip(0)
  }, [])

  const clearFilters = useCallback(() => {
    setFilters({})
    setSearchInput('')
    setDatePreset('all')
    setSkip(0)
  }, [])

  const handleSearchChange = useCallback((value: string) => {
    setSearchInput(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => applyFilter({ search: value || undefined }), 300)
  }, [applyFilter])

  const handleDatePreset = useCallback((preset: DatePreset) => {
    setDatePreset(preset)
    applyFilter({ date_from: presetToDateFrom(preset), date_to: undefined })
  }, [applyFilter])

  // ── Sort + Group ──────────────────────────────────────────────────────────────
  const [sort, setSort]       = useState<SortConfig>({ field: 'date', dir: 'desc' })
  const [groupBy, setGroupBy] = useState<GroupBy>('none')

  // ── Selection mode ────────────────────────────────────────────────────────────
  const [selectionMode, setSelectionMode]   = useState(false)
  const [selectedIds, setSelectedIds]       = useState<Set<string>>(new Set())
  const [fetchAllIds, setFetchAllIds]       = useState(false)
  const { mutate: bulkSync, isPending: bulkSyncing } = useBulkSyncActivities()

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }, [])

  const exitSelection = useCallback(() => {
    setSelectionMode(false)
    setSelectedIds(new Set())
    setFetchAllIds(false)
  }, [])

  const { data: allIdsData, isFetching: fetchingIds } = useActivityIds(filters, fetchAllIds)

  useEffect(() => {
    if (allIdsData && fetchAllIds) {
      setSelectedIds(new Set(allIdsData.ids))
      setFetchAllIds(false)
    }
  }, [allIdsData, fetchAllIds])

  // ── UI state ──────────────────────────────────────────────────────────────────
  const [selected, setSelected]     = useState<Activity | null>(null)
  const [showImport, setShowImport] = useState(false)

  const { data, isLoading, isFetching } = useActivities({ skip, limit: PAGE_SIZE, filters })
  const rawActivities = useMemo(() => data?.data ?? [], [data])
  const hasPrev       = skip > 0
  const hasNext       = (data?.count ?? 0) === PAGE_SIZE

  // Apply sort + group client-side (within current page)
  const sortedActivities = useMemo(() => sortActivities(rawActivities, sort), [rawActivities, sort])
  const groupedData      = useMemo(() => groupActivities(sortedActivities, groupBy), [sortedActivities, groupBy])

  const allOnPageSelected  = rawActivities.length > 0 && rawActivities.every((a) => selectedIds.has(a.id))
  const someOnPageSelected = rawActivities.some((a) => selectedIds.has(a.id)) && !allOnPageSelected

  const toggleSelectAll = useCallback(() => {
    if (allOnPageSelected) {
      setSelectedIds((prev) => {
        const next = new Set(prev)
        rawActivities.forEach((a) => next.delete(a.id))
        return next
      })
    } else {
      setSelectedIds((prev) => {
        const next = new Set(prev)
        rawActivities.forEach((a) => next.add(a.id))
        return next
      })
    }
  }, [allOnPageSelected, rawActivities])

  const handleBulkSync = useCallback((dest: PlatformKey) => {
    bulkSync({ ids: Array.from(selectedIds), destination: dest }, { onSuccess: exitSelection })
  }, [bulkSync, selectedIds, exitSelection])

  const activeFilterCount = Object.keys(filters).length
  const isFiltered        = activeFilterCount > 0

  return (
    <>
      <div className="space-y-4">
        {/* Page header */}
        <div>
          <h1 className="text-heading-lg text-text-primary font-bold">Activities</h1>
          <p className="text-body-sm text-text-secondary mt-1">
            All your synced and imported activities in one place.
          </p>
        </div>

        {/* Toolbar */}
        <Toolbar
          searchInput={searchInput}
          filters={filters}
          sort={sort}
          groupBy={groupBy}
          datePreset={datePreset}
          connectedPlatforms={connectedPlatforms}
          isSyncing={isSyncing}
          syncedAt={syncStatus?.last_successful_sync_at ?? null}
          selectionMode={selectionMode}
          onSearchChange={handleSearchChange}
          onFilterChange={applyFilter}
          onClearFilters={clearFilters}
          onSort={setSort}
          onGroupBy={setGroupBy}
          onDatePreset={handleDatePreset}
          onRefresh={handleManualRefresh}
          onToggleSelect={() => selectionMode ? exitSelection() : setSelectionMode(true)}
          onImport={() => setShowImport(true)}
        />

        {/* Aggregate overview — reacts to the active filters */}
        <ActivityOverview filters={filters} />

        {/* Card */}
        <Card>
          <CardHeader className="border-b border-border pb-3 pt-4">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-2.5">
                <CardTitle className="text-text-primary">
                  {isFiltered ? 'Filtered results' : 'All activities'}
                </CardTitle>
                {(isFetching && !isLoading) && (
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-text-disabled" />
                )}
              </div>
              <div className="flex items-center gap-3">
                {selectionMode && rawActivities.length > 0 && (
                  <label className="flex items-center gap-2 text-body-sm text-text-secondary cursor-pointer">
                    <input
                      type="checkbox"
                      checked={allOnPageSelected}
                      ref={(el) => { if (el) el.indeterminate = someOnPageSelected }}
                      onChange={toggleSelectAll}
                      className="w-4 h-4 rounded border-border accent-primary cursor-pointer"
                    />
                    <span className="text-caption hidden sm:inline">Select page</span>
                  </label>
                )}
              </div>
            </div>
          </CardHeader>

          {/* "Select all matching" banner */}
          {selectionMode && (isFiltered || rawActivities.length > 0) && (
            <div className="flex items-center justify-between gap-4 px-6 py-2.5 bg-primary/5 border-b border-primary/20 text-caption">
              <span className="text-text-secondary">
                {selectedIds.size > 0
                  ? `${selectedIds.size} activit${selectedIds.size === 1 ? 'y' : 'ies'} selected`
                  : 'Select activities, or select all matching this filter across all pages.'}
              </span>
              <button
                onClick={() => setFetchAllIds(true)}
                disabled={fetchingIds}
                className="flex items-center gap-1.5 text-primary font-medium hover:underline disabled:opacity-50 flex-shrink-0"
              >
                {fetchingIds && <Loader2 className="w-3 h-3 animate-spin" />}
                Select all matching
              </button>
            </div>
          )}

          <CardContent className="p-0">
            {isLoading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="w-6 h-6 animate-spin text-text-disabled" />
              </div>
            ) : rawActivities.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-center px-6">
                <div className="w-12 h-12 rounded-full bg-surface-raised flex items-center justify-center mb-4">
                  <Upload className="w-6 h-6 text-text-disabled" />
                </div>
                <p className="text-body text-text-primary font-medium">
                  {isFiltered ? 'No activities match your filters' : 'No activities yet'}
                </p>
                <p className="text-body-sm text-text-secondary mt-1">
                  {isFiltered
                    ? 'Try adjusting or clearing your filters.'
                    : 'Sync your first activity or import a GPX file.'}
                </p>
                {isFiltered && (
                  <Button variant="secondary" size="sm" className="mt-4" onClick={clearFilters}>
                    Clear filters
                  </Button>
                )}
              </div>
            ) : (
              <div>
                {groupedData.map(({ key, label, items }) => (
                  <div key={key}>
                    {groupBy !== 'none' && <GroupHeader label={label} count={items.length} />}
                    {items.map((act) => (
                      <ActivityRow
                        key={act.id}
                        act={act}
                        connectedPlatforms={connectedPlatforms}
                        selectionMode={selectionMode}
                        selected={selectedIds.has(act.id)}
                        onToggle={() => toggleSelect(act.id)}
                        onClick={() => { if (!selectionMode) setSelected(act) }}
                      />
                    ))}
                  </div>
                ))}
              </div>
            )}
          </CardContent>

          {(hasPrev || hasNext) && (
            <CardFooter className="flex items-center justify-between gap-4 py-3 border-t border-border">
              <Button variant="ghost" size="sm" disabled={!hasPrev}
                onClick={() => setSkip(Math.max(0, skip - PAGE_SIZE))}>
                <ChevronLeft className="w-4 h-4" />Previous
              </Button>
              <span className="text-caption text-text-disabled tabular-nums">
                {skip + 1}–{skip + rawActivities.length}
              </span>
              <Button variant="ghost" size="sm" disabled={!hasNext}
                onClick={() => setSkip(skip + PAGE_SIZE)}>
                Next<ChevronRight className="w-4 h-4" />
              </Button>
            </CardFooter>
          )}
        </Card>
      </div>

      {showImport && <ImportPanel onClose={() => setShowImport(false)} />}
      {selected && (
        <ActivityDetail
          act={selected}
          connectedPlatforms={connectedPlatforms}
          onClose={() => setSelected(null)}
        />
      )}

      <BulkActionBar
        count={selectedIds.size}
        connectedPlatforms={connectedPlatforms}
        loading={bulkSyncing}
        onSync={handleBulkSync}
        onCancel={exitSelection}
      />
    </>
  )
}
