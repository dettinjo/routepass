// RoutePass — API response types
// These mirror the Pydantic response schemas from backend/app/api/v1/*.py.
// Keep in sync when the backend schema changes.

// ── Auth ─────────────────────────────────────────────────────────────────────

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
}

export interface UserMe {
  id: string
  email: string
  name?: string | null
  created_at: string
  // Connection status
  komoot_connected: boolean
  strava_connected: boolean
  intervals_connected: boolean
  runalyze_connected: boolean
  polar_connected: boolean
  outdooractive_connected: boolean
  // Sync preferences
  sync_komoot_to_strava: boolean
  komoot_poll_interval_min: number
  // Subscription
  tier: 'free' | 'pro'
  subscription?: Subscription
}

// ── Subscription ──────────────────────────────────────────────────────────────

export interface Subscription {
  id: string
  tier: 'free' | 'pro'
  status: 'active' | 'trialing' | 'past_due' | 'canceled'
  current_period_end: string | null
  stripe_customer_id: string | null
}

// ── Sync ──────────────────────────────────────────────────────────────────────

export type SyncStatus = 'idle' | 'syncing' | 'error' | 'paused'
export type SyncDirection =
  | 'komoot_to_strava'
  | 'strava_to_komoot'
  | 'komoot_to_intervals'
  | 'strava_to_intervals'
  | 'komoot_to_runalyze'

export interface SyncState {
  status: SyncStatus
  last_synced_at: string | null
  last_activity_name: string | null
  last_activity_id: string | null
  error_message: string | null
  daily_strava_calls_used: number
  daily_strava_calls_limit: number
}

// ── Activities ────────────────────────────────────────────────────────────────

export type ActivitySyncStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'conflict'

export interface Activity {
  id: string
  /** Origin of the activity: 'komoot' | 'strava' | 'import' */
  source: string
  komoot_tour_id: string | null
  strava_activity_id: string | null
  activity_name: string | null
  sport_type: string | null
  distance_m: number | null
  duration_seconds: number | null
  elevation_up_m: number | null
  started_at: string | null
  sync_direction: string | null
  sync_status: ActivitySyncStatus
  conflict_reason: string | null
  resolved_at: string | null
  synced_at: string
  /** Which platforms this activity is present on (e.g. ["komoot", "strava"]) */
  platforms: string[]
  /** True if the activity is synced between 2 or more platforms */
  is_synced: boolean
  /** True if a GPX track is available for this activity */
  has_gpx: boolean
}

// ── Activity filters ──────────────────────────────────────────────────────────

export interface ActivityFilters {
  source?: 'komoot' | 'strava' | 'import'
  sync_status?: 'pending' | 'completed' | 'failed' | 'conflict'
  sport_type?: string
  search?: string
  synced?: boolean
  /** ISO datetime string — filter by started_at ≥ this value */
  date_from?: string
  /** ISO datetime string — filter by started_at ≤ this value */
  date_to?: string
}

export interface SeedResult {
  created: number
  skipped_existing: number
  total: number
}

export interface ImportResult {
  created: { id: string; name: string }[]
  errors: { file: string; error: string }[]
}

export interface ActivitiesResponse {
  data: Activity[]
  skip: number
  limit: number
  count: number
}

// ── Connections ───────────────────────────────────────────────────────────────

import type { PlatformKey as _PlatformKey } from '@/components/platform-icons'
export type { PlatformKey } from '@/components/platform-icons'

export interface Connection {
  id: string
  platform: _PlatformKey
  display_name: string
  status: 'active' | 'error' | 'disconnected'
  last_synced_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
}

// ── Pipelines ─────────────────────────────────────────────────────────────────

export interface Pipeline {
  id: string
  user_id: string
  source_connection_id: string
  dest_connection_id: string
  name: string
  enabled: boolean
  created_at: string
  updated_at: string
}

// ── Rules ─────────────────────────────────────────────────────────────────────
// conditions and actions are free-form JSON dicts evaluated by sync.py.
// Common condition keys: sport_type, distance_km, elevation_m, name_contains
// Common action keys:    skip, set_sport_type, name_template, append_description, set_hide_from_home

export interface SyncRule {
  id: string
  name: string
  is_active: boolean
  direction: 'komoot_to_strava' | 'strava_to_komoot' | 'both'
  rule_order: number
  conditions: Record<string, unknown>
  actions: Record<string, unknown>
  created_at?: string
}

// ── API Keys ──────────────────────────────────────────────────────────────────

export interface ApiKey {
  id: string
  name: string
  key_prefix: string    // first 8 chars + "...", for display
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

export interface ApiKeyCreated {
  id: string
  name: string
  key_prefix: string
  raw_key: string       // returned once at creation, never again
  message: string
}

// ── Billing ───────────────────────────────────────────────────────────────────

export interface BillingSubscription {
  tier: 'free' | 'pro' | 'lifetime'
  status: 'active' | 'trialing' | 'past_due' | 'canceled'
  stripe_customer_id: string | null
  stripe_subscription_id: string | null
  current_period_start: string | null
  current_period_end: string | null
  trial_ends_at: string | null
  canceled_at: string | null
  activities_synced_this_period: number
}

// ── Generic ───────────────────────────────────────────────────────────────────

export interface ApiError {
  detail: string
}

export interface MessageResponse {
  message: string
}
