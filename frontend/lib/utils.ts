import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import sportMappings from '../../shared/sport-mappings.json'

// Merge Tailwind classes without conflicts — use everywhere instead of raw clsx
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Format a date as a human-readable relative string ("2 hours ago")
export function formatRelative(date: Date | string): string {
  const d = typeof date === 'string' ? new Date(date) : date
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60_000)

  if (diffMin < 1)   return 'just now'
  if (diffMin < 60)  return `${diffMin}m ago`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24)    return `${diffH}h ago`
  const diffD = Math.floor(diffH / 24)
  if (diffD < 7)     return `${diffD}d ago`
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

// Format a date as "12 Jan 2025 · 09:41"
export function formatDateTime(date: Date | string): string {
  const d = typeof date === 'string' ? new Date(date) : date
  return d.toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Format distance in metres → "12.4 km" or "850 m"
export function formatDistance(metres: number): string {
  if (metres >= 1000) return `${(metres / 1000).toFixed(1)} km`
  return `${Math.round(metres)} m`
}

// Format duration in seconds → "1h 23m" or "45m"
export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h === 0) return `${m}m`
  if (m === 0) return `${h}h`
  return `${h}h ${m}m`
}

export const SPORT_LABELS: Record<string, string> = sportMappings.labels
export function sportLabel(sportType: string): string {
  return SPORT_LABELS[sportType] ?? sportType
}

// Truncate a string with ellipsis at a given length
export function truncate(str: string, max: number): string {
  return str.length > max ? `${str.slice(0, max)}…` : str
}

// Mask an API key for display — show first 8 chars + "••••••••"
export function maskApiKey(key: string): string {
  return `${key.slice(0, 8)}••••••••`
}

// Any non-free tier grants Pro-level features (pro, business, lifetime, comped operator).
export function isPaidTier(tier?: string | null): boolean {
  return !!tier && tier !== 'free'
}

// Format integer cents as a currency string, e.g. 499 -> "$4.99"
export function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`
}
