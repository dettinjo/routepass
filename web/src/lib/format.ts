export const km = (m?: number | null, digits = 1) =>
  m == null ? "–" : (m / 1000).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: m >= 100000 ? 0 : digits });

export const int = (v?: number | null) => (v == null ? "–" : Math.round(v).toLocaleString());

export const num = (v?: number | null, digits = 1) =>
  v == null ? "–" : v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });

export function duration(s?: number | null, withSeconds = false): string {
  if (s == null) return "–";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.round(s % 60);
  if (withSeconds) return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

export const hours = (s?: number | null) => (s == null ? "–" : (s / 3600).toLocaleString(undefined, { maximumFractionDigits: 1 }));

/** Pace for foot sports (min/km), speed for everything else (km/h). */
export function speed(ms: number | null | undefined, family: string): string {
  if (!ms) return "–";
  if (family === "run" || family === "walk") {
    const secPerKm = 1000 / ms;
    return `${Math.floor(secPerKm / 60)}:${String(Math.round(secPerKm % 60)).padStart(2, "0")} /km`;
  }
  return `${(ms * 3.6).toFixed(1)} km/h`;
}

export function date(iso?: string | null, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", year: "numeric" }) {
  if (!iso) return "–";
  return new Date(iso).toLocaleDateString(undefined, opts);
}

export function dateTime(iso?: string | null) {
  if (!iso) return "–";
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Wall-clock time of the activity: start_local is naive local time, start_time is UTC. */
export function activityDate(a: { start_local?: string | null; start_time: string }, withTime = true) {
  const d = a.start_local ? new Date(a.start_local + (a.start_local.endsWith("Z") ? "" : "Z")) : new Date(a.start_time);
  const tz = a.start_local ? "UTC" : undefined;
  return d.toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short", year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}), timeZone: tz,
  });
}

export function ago(iso?: string | null): string {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export function pctDelta(cur: number, prev: number): number | null {
  if (!prev) return null;
  return ((cur - prev) / prev) * 100;
}

export const isoDay = (d: Date) => d.toISOString().slice(0, 10);
