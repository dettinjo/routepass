import { Link } from "react-router-dom";
import { FAMILIES, FAMILY_LABEL, familyColor } from "../lib/colors";
import { activityDate, duration, hours, int, km, speed } from "../lib/format";
import { decodePolyline } from "../lib/polyline";
import type { ActivityRow } from "../lib/types";
import { RouteThumb } from "./charts";
import { ICON, IconLock, IconRight, MetricIcon, SportIcon } from "./icons";
import { ProviderBadges, SportBadge } from "./ui";
import { VisibilityMark } from "./ActivityMedia";

export type Metric = "distance_m" | "moving_time_s" | "elevation_m" | "count" | "load";
export const METRICS: { value: Metric; label: string }[] = [
  { value: "distance_m", label: "Distance" },
  { value: "moving_time_s", label: "Time" },
  { value: "elevation_m", label: "Elevation" },
  { value: "load", label: "Load" },
  { value: "count", label: "Count" },
];
export const metricFormat = (m: Metric) => (v: number) =>
  m === "distance_m" ? `${km(v, 0)} km` : m === "moving_time_s" ? `${hours(v)} h` : m === "elevation_m" ? `${int(v)} m` : int(v);

export function FamilyChips({ value, onChange, wrap = false }: { value: string[]; onChange: (v: string[]) => void; wrap?: boolean }) {
  return (
    <div className="chips" role="group" aria-label="Sport filter" style={wrap ? { flexWrap: "wrap" } : undefined}>
      <button className={`chip ${value.length === 0 ? "on" : ""}`} onClick={() => onChange([])}>All sports</button>
      {FAMILIES.map((f) => (
        <button key={f} className={`chip ${value.includes(f) ? "on" : ""}`}
          onClick={() => onChange(value.includes(f) ? value.filter((x) => x !== f) : [...value, f])}>
          <SportIcon family={f} size={15} style={{ color: familyColor(f) }} />{FAMILY_LABEL[f]}
        </button>
      ))}
    </div>
  );
}

/** One activity as a tappable row: sport, name, when, key numbers, where it exists. */
export function ActivityItem({ a, selectable = false, selected = false, onToggle }: {
  a: ActivityRow; selectable?: boolean; selected?: boolean; onToggle?: (id: number) => void;
}) {
  const content = (
    <>
      {selectable && (
        <input type="checkbox" checked={selected} aria-label={`Select ${a.name}`}
          onClick={(e) => e.stopPropagation()} onChange={() => onToggle?.(a.id)} />
      )}
      <SportBadge sport={a.sport} family={a.family} />
      <div className="main-col">
        <div className="row nowrap" style={{ gap: 6 }}>
          <span className="name ellipsis">{a.name}</span>
          {a.sync_locked && <IconLock size={ICON.inline} className="muted" />}
          <VisibilityMark v={a.visibility} />
        </div>
        <span className="meta ellipsis">{a.sport_label} · {activityDate(a)}{a.trainer ? " · indoor" : ""}{a.commute ? " · commute" : ""}</span>
        <div className="metrics">
          {a.distance_m ? <span><MetricIcon.distance size={ICON.inline} />{km(a.distance_m)} km</span> : null}
          <span><MetricIcon.time size={ICON.inline} />{duration(a.moving_time_s)}</span>
          {a.elevation_gain_m ? <span><MetricIcon.elevation size={ICON.inline} />{int(a.elevation_gain_m)} m</span> : null}
          {a.avg_speed_ms ? <span className="extra"><MetricIcon.speed size={ICON.inline} />{speed(a.avg_speed_ms, a.family)}</span> : null}
          {a.avg_hr ? <span className="extra"><MetricIcon.hr size={ICON.inline} />{int(a.avg_hr)}</span> : null}
          {a.avg_power ? <span className="extra"><MetricIcon.power size={ICON.inline} />{int(a.avg_power)} W</span> : null}
        </div>
      </div>
      <div className="side">
        <ProviderBadges providers={a.providers} copies={a.copies} />
        <span className="route-thumb"><RouteThumb points={a.polyline ? decodePolyline(a.polyline) : []} color={familyColor(a.family)} size={34} /></span>
      </div>
      {!selectable && <IconRight size={ICON.header} className="muted hide-mobile" />}
    </>
  );
  if (selectable) {
    return <div className={`item ${selected ? "selected" : ""}`} role="button" tabIndex={0} onClick={() => onToggle?.(a.id)}>{content}</div>;
  }
  return <Link to={`/activities/${a.id}`} className="item">{content}</Link>;
}

export function ActivityList({ items, compact: _compact }: { items: ActivityRow[]; compact?: boolean }) {
  return <div className="list">{items.map((a) => <ActivityItem key={a.id} a={a} />)}</div>;
}

export { FAMILY_LABEL };
