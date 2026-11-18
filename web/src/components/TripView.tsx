import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "../lib/api";
import { familyColor } from "../lib/colors";
import { duration, int, km, speed } from "../lib/format";
import { decodePolyline } from "../lib/polyline";
import type { ActivityRow } from "../lib/types";
import { StackedBars } from "./charts";
import { RoutesMap } from "./maps";
import { Modal, Skeleton, Stat } from "./ui";
import { ActivityList } from "./shared";

interface Trip {
  activities: ActivityRow[];
  days: { date: string; activities: number; distance_m: number; moving_time_s: number; elevation_m: number }[];
  totals: { distance_m: number; moving_time_s: number; elevation_m: number; load: number; count: number; days: number; span_days: number; avg_per_day_m: number; avg_speed_ms: number | null };
  longest_day: string;
  most_climbing_day: string;
}

export function TripView({ ids, onClose }: { ids: number[]; onClose: () => void }) {
  const { data, error } = useQuery<Trip>({ queryKey: ["trip", ids], queryFn: () => api("/activities/trip", { method: "POST", body: { activity_ids: ids } }) });
  const routes = useMemo(() => (data?.activities || []).map((a) => ({ id: a.id, family: a.family, points: a.polyline ? decodePolyline(a.polyline) : [] })), [data]);
  const fam = data?.activities[0]?.family ?? "ride";
  const multiYear = data ? new Set(data.days.map((d) => d.date.slice(0, 4))).size > 1 : false;
  const fmtDay = (d: string) =>
    new Date(d).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", ...(multiYear ? { year: "numeric" } : {}) });
  return (
    <Modal title="Trip overview" onClose={onClose}>
      {error ? <div className="callout bad">{(error as Error).message}</div> : !data ? <Skeleton h={400} /> : (
        <>
          <div className="stats">
            <Stat label="Distance" value={km(data.totals.distance_m, 0)} unit="km" />
            <Stat label="Moving time" value={duration(data.totals.moving_time_s)} />
            <Stat label="Elevation" value={int(data.totals.elevation_m)} unit="m" />
            <Stat label="Days" value={data.totals.days} unit={`/ ${data.totals.span_days} d`} />
            <Stat label="Per day" value={km(data.totals.avg_per_day_m, 0)} unit="km" />
            <Stat label="Avg speed" value={speed(data.totals.avg_speed_ms, fam)} />
          </div>
          <RoutesMap routes={routes} opacity={0.9} weight={3} />
          <div>
            <div className="section-label">Distance per day</div>
            <StackedBars
              height={160}
              data={data.days.map((d) => ({ label: `${fmtDay(d.date)} · ${int(d.elevation_m)} m up · ${duration(d.moving_time_s)}`, values: { d: d.distance_m } }))}
              series={[{ key: "d", label: "Distance", color: familyColor(fam) }]}
              format={(v) => `${km(v, 0)} km`}
              labelFor={(i) => fmtDay(data.days[i].date)}
            />
            <p className="small muted" style={{ margin: "8px 0 0" }}>Longest day {fmtDay(data.longest_day)} · most climbing {fmtDay(data.most_climbing_day)}</p>
          </div>
          <ActivityList items={data.activities} compact />
        </>
      )}
    </Modal>
  );
}
