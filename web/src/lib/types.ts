export interface ActivityRow {
  id: number; name: string; sport: string; sport_label: string; family: string;
  start_time: string; start_local: string | null;
  distance_m: number | null; moving_time_s: number | null; elevation_gain_m: number | null;
  avg_speed_ms: number | null; avg_hr: number | null; avg_power: number | null; load: number | null;
  has_track: boolean; trainer: boolean; commute: boolean; polyline: string | null;
  providers: string[]; copies: string[]; sync_locked: boolean;
  visibility?: { by_provider: Record<string, string | null>; mismatch: boolean };
}

export interface Source {
  id: number; provider: string; external_id: string; url: string; name: string; sport: string;
  start_time: string; distance_m: number | null; created_by_sync: boolean; match_locked: boolean;
  deleted: boolean; track_status: string; visibility: string | null;
}

export interface SyncJob {
  id: number; activity_id: number; direction: string; source_provider: string; source_id: string;
  target_provider: string; target_id: string | null; target_url: string | null; status: string;
  rule_id: number | null; plan: Record<string, any>; reason: string | null; error: string | null;
  attempts: number; next_attempt_at: string | null; created_at: string; updated_at: string;
  activity?: { name: string; sport: string; start_time: string; distance_m: number | null };
}

export interface ActivityDetail extends ActivityRow {
  description: string; elapsed_time_s: number | null; elevation_loss_m: number | null; elevation_max_m: number | null;
  max_speed_ms: number | null; max_hr: number | null; normalized_power: number | null; max_power: number | null;
  avg_cadence: number | null; avg_temp: number | null; calories: number | null; work_kj: number | null;
  load_method: string | null; intensity: number | null; device: string | null; gear: string | null;
  track_provider: string | null; sources: Source[]; sync_jobs: SyncJob[];
  sync_status: Record<string, string | null>; prev_id: number | null; next_id: number | null;
  tiles?: { tiles_visited: number; new_tiles: number };
  analysis: null | {
    channels: string[];
    hr_zones?: { bounds: number[]; seconds: number[]; basis: string };
    power_zones?: { bounds: number[]; seconds: number[]; ftp: number };
    splits?: { index: number; distance_m: number; duration_s: number; speed_ms: number | null; gap_speed_ms?: number | null; hr: number | null; power: number | null; gain_m: number; loss_m: number }[];
    split_m?: number;
    climbs?: { start_m: number; end_m: number; length_m: number; gain_m: number; grade_pct: number; duration_s: number; vam: number | null; top_m: number }[];
    power_curve?: Record<string, number>;
    best_times?: Record<string, number>;
    decoupling?: { metric: string; pct: number };
    temp_range?: [number | null, number | null];
    summary?: { gap_speed_ms?: number | null; effort_km?: number | null; [k: string]: any };
  };
}

export interface TrackPoint { t: number; d: number | null; ele: number | null; hr: number | null; pw: number | null; cad: number | null; v: number | null; gap?: number | null; temp: number | null; lat: number | null; lon: number | null }

export interface Totals { count: number; distance_m: number; moving_time_s: number; elevation_m: number; load: number; work_kj: number; active_days?: number }

export interface Rule {
  id: number; name: string; direction: string; enabled: boolean; priority: number;
  conditions: Record<string, any>; actions: Record<string, any>; match_count: number; last_matched_at: string | null;
}

export interface TrailRaceGoal {
  name: string;
  date: string | null;
  distance_km: number;
  elevation_gain_m: number;
  weekly_km_target: number;
  weekly_vert_target: number;
  target_carbs_g_per_h: number;
}

export interface Preferences {
  sync: {
    auto: boolean; start_date: string | null; delay_minutes: number;
    strava_to_komoot: DirectionPrefs; komoot_to_strava: DirectionPrefs;
  };
  matching: { time_tolerance_min: number; distance_tolerance_pct: number };
  profile: { ftp: number | null; hr_max: number | null; hr_rest: number | null; weight_kg: number | null };
  import: { history_start: string | null };
  poll_interval_minutes: number | null;
  goals: Record<string, number | null>;
  gear_targets: Record<string, { label?: string; service_km?: number | null }>;
  places: Place[];
  trail_race?: TrailRaceGoal;
}
export interface DirectionPrefs { enabled: boolean; default_action: "sync" | "skip"; sync_photos?: boolean; match_visibility?: boolean; defaults: Record<string, any> }

export interface SyncRun { id: number; trigger: string; status: string; started_at: string; finished_at: string | null; stats: Record<string, any>; log: string[] }

export interface Status {
  public_url: string | null;
  connections: {
    strava: { connected: boolean; mode?: "oauth" | "web" | "oauth+web" | null; athlete: any; error: ProviderError | null };
    komoot: { connected: boolean; account: any; error: ProviderError | null };
  };
  running: boolean; last_run: SyncRun | null; jobs: Record<string, number>; activities: number; tracks_pending: number;
  coverage: { both: number; strava_only: number; komoot_only: number; activities: number; duplicates_hidden: number; provider_records: Record<string, number> };
  strava_rate: { overall: Record<string, [number, number]>; read: Record<string, [number, number]>; observed_at: string | null };
  imports: Record<string, any>;
}

export interface ProviderError { message: string; at: string; hint: string }

export interface Place { name: string; lat: number; lng: number; radius_km: number }
