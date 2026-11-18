import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Legend, LineChart, RouteThumb, StackedBars } from "../components/charts";
import { Card, ProviderBadges, Seg, Skeleton, SportDot, Stat } from "../components/ui";
import { api } from "../lib/api";
import { FAMILIES, FAMILY_LABEL, familyColor } from "../lib/colors";
import { activityDate, duration, hours, int, km, pctDelta } from "../lib/format";
import { useStatus } from "../lib/hooks";
import { decodePolyline } from "../lib/polyline";
import type { ActivityRow, Totals } from "../lib/types";

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

export function FamilyChips({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="row" style={{ gap: 6 }}>
      <button className={`chip ${value.length === 0 ? "on" : ""}`} onClick={() => onChange([])}>All</button>
      {FAMILIES.map((f) => (
        <button key={f} className={`chip ${value.includes(f) ? "on" : ""}`}
          onClick={() => onChange(value.includes(f) ? value.filter((x) => x !== f) : [...value, f])}>
          <span className="dot" style={{ background: familyColor(f) }} />{FAMILY_LABEL[f]}
        </button>
      ))}
    </div>
  );
}

function PeriodCard({ title, cur, prev }: { title: string; cur: Totals; prev: Totals }) {
  return (
    <Card title={title}>
      <div className="stats" style={{ gridTemplateColumns: "repeat(2, minmax(0,1fr))" }}>
        <Stat label="Distance" value={km(cur.distance_m, 0)} unit="km" delta={pctDelta(cur.distance_m, prev.distance_m)} />
        <Stat label="Moving time" value={duration(cur.moving_time_s)} delta={pctDelta(cur.moving_time_s, prev.moving_time_s)} />
        <Stat label="Elevation" value={int(cur.elevation_m)} unit="m" delta={pctDelta(cur.elevation_m, prev.elevation_m)} />
        <Stat label="Activities" value={cur.count} delta={pctDelta(cur.count, prev.count)} />
      </div>
    </Card>
  );
}

export function ActivityList({ items, compact = false }: { items: ActivityRow[]; compact?: boolean }) {
  const nav = useNavigate();
  return (
    <div className="table-wrap">
      <table>
        <tbody>
          {items.map((a) => (
            <tr key={a.id} className="click" onClick={() => nav(`/activities/${a.id}`)}>
              <td style={{ width: 52 }}><RouteThumb points={a.polyline ? decodePolyline(a.polyline) : []} color={familyColor(a.family)} /></td>
              <td>
                <div className="name-cell" style={{ minWidth: 0 }}><span className="t">{a.name}</span></div>
                <div className="small muted row" style={{ gap: 6 }}><SportDot family={a.family} />{a.sport_label} · {activityDate(a)}</div>
              </td>
              <td className="r" style={{ whiteSpace: "nowrap" }}>{km(a.distance_m)} km{compact && <div className="small muted">{duration(a.moving_time_s)}</div>}</td>
              {!compact && <td className="r">{duration(a.moving_time_s)}</td>}
              {!compact && <td className="r">{int(a.elevation_gain_m)} m</td>}
              <td className="r" style={{ width: 60 }}><ProviderBadges providers={a.providers} copies={a.copies} all /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Dashboard() {
  const [families, setFamilies] = useState<string[]>([]);
  const [metric, setMetric] = useState<Metric>("distance_m");
  const nav = useNavigate();
  const { data: status } = useStatus();
  const { data, isLoading } = useQuery<any>({
    queryKey: ["dashboard", families],
    queryFn: () => api("/insights/dashboard", { params: { family: families } }),
  });

  const weekly = useMemo(() => {
    if (!data) return null;
    const groups: string[] = data.weekly.groups;
    const buckets = data.weekly.buckets.slice(-53);
    return {
      series: FAMILIES.filter((f) => groups.includes(f)).map((f) => ({ key: f, label: FAMILY_LABEL[f], color: familyColor(f) })),
      bars: buckets.map((b: any) => ({
        label: `Week of ${new Date(b.start).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}`,
        values: Object.fromEntries(Object.entries(b.groups).map(([k, v]: [string, any]) => [k, v[metric]])),
        start: b.start,
      })),
    };
  }, [data, metric]);

  const load = data?.load;
  const loadChart = useMemo(() => {
    if (!load?.series?.length) return null;
    return {
      x: load.series.map((p: any) => new Date(p.date).getTime() / 1000),
      series: [
        { label: "Fitness (CTL)", color: "var(--series-1)", values: load.series.map((p: any) => p.ctl), fill: true },
        { label: "Fatigue (ATL)", color: "var(--series-2)", values: load.series.map((p: any) => p.atl) },
      ],
    };
  }, [load]);

  const notConnected = status && (!status.connections.strava.connected || !status.connections.komoot.connected);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <div className="sub">
            {status ? <>{int(status.coverage.activities)} activities · {int(status.coverage.duplicates_hidden)} cross-platform duplicates merged</> : " "}
          </div>
        </div>
        <FamilyChips value={families} onChange={setFamilies} />
      </div>

      {notConnected && (
        <div className="callout warn" style={{ marginBottom: 16 }}>
          {!status!.connections.strava.connected && "Strava is not connected. "}
          {!status!.connections.komoot.connected && "Komoot is not connected. "}
          <Link to="/settings">Connect in Settings →</Link>
        </div>
      )}

      {isLoading || !data ? (
        <div className="grid g3"><Skeleton h={160} /><Skeleton h={160} /><Skeleton h={160} /></div>
      ) : (
        <div className="stack gap16">
          <div className="grid g3">
            <PeriodCard title="This week" cur={data.periods.week.current} prev={data.periods.week.previous} />
            <PeriodCard title="This month" cur={data.periods.month.current} prev={data.periods.month.previous} />
            <PeriodCard title="Year to date" cur={data.periods.year.current} prev={data.periods.year.previous} />
          </div>

          <Card title="Weekly volume" hint="Last 12 months — click a week to see its activities"
            actions={<Seg value={metric} options={METRICS} onChange={setMetric} />}>
            {weekly && weekly.bars.length ? (
              <>
                <StackedBars
                  data={weekly.bars}
                  series={weekly.series}
                  format={metricFormat(metric)}
                  labelFor={(i) => {
                    const m = (j: number) => new Date(weekly.bars[j].start).getMonth();
                    return i === 0 || m(i) !== m(i - 1) ? new Date(weekly.bars[i].start).toLocaleDateString(undefined, { month: "short" }) : "";
                  }}
                  onClick={(i) => {
                    const s = new Date(weekly.bars[i].start);
                    const e = new Date(s.getTime() + 6 * 86400000);
                    nav(`/activities?start=${weekly.bars[i].start}&end=${e.toISOString().slice(0, 10)}`);
                  }}
                />
                {weekly.series.length > 1 && <div className="mt8"><Legend items={weekly.series} /></div>}
              </>
            ) : <div className="empty">No activities yet</div>}
          </Card>

          <div className="grid g3">
            <Card title="Form" hint="Fitness 42 d · fatigue 7 d · form = fitness − fatigue" className="span2"
              actions={load?.current && <span className={`badge ${{ fresh: "good", transition: "info", neutral: "", productive: "info", overreaching: "bad" }[load.status as string] ?? ""}`}>{load.status}</span>}>
              {load?.current ? (
                <>
                  <div className="stats" style={{ marginBottom: 12 }}>
                    <Stat label="Fitness" value={load.current.ctl.toFixed(0)} />
                    <Stat label="Fatigue" value={load.current.atl.toFixed(0)} />
                    <Stat label="Form" value={load.current.tsb.toFixed(0)} />
                    <Stat label="7-day ramp" value={load.ramp_7d != null ? (load.ramp_7d > 0 ? "+" : "") + load.ramp_7d.toFixed(1) : "–"} />
                  </div>
                  {loadChart && <LineChart x={loadChart.x} series={loadChart.series} xTime height={180} yFormat={(v) => v.toFixed(0)} />}
                  <div className="mt8 row between">
                    <Legend line items={[{ key: "ctl", label: "Fitness (CTL)", color: "var(--series-1)" }, { key: "atl", label: "Fatigue (ATL)", color: "var(--series-2)" }]} />
                    <Link to="/insights/fitness" className="small">Full history →</Link>
                  </div>
                </>
              ) : <div className="empty">No training load yet</div>}
            </Card>
            <Card title="Consistency">
              <div className="stats" style={{ gridTemplateColumns: "repeat(2, minmax(0,1fr))" }}>
                <Stat label="Day streak" value={data.streaks.current_days} unit="d" />
                <Stat label="Longest" value={data.streaks.longest_days} unit="d" />
                <Stat label="Week streak" value={data.streaks.current_weeks} unit="wk" />
                <Stat label="Longest" value={data.streaks.longest_weeks} unit="wk" />
              </div>
              <div className="mt16 section-label">Platforms</div>
              <dl className="kv mt8">
                <dt>On both</dt><dd>{int(data.coverage.both)}</dd>
                <dt>Strava only</dt><dd>{int(data.coverage.strava_only)}</dd>
                <dt>Komoot only</dt><dd>{int(data.coverage.komoot_only)}</dd>
              </dl>
            </Card>
          </div>

          <Card title="Recent activities" actions={<Link to="/activities" className="small">All activities →</Link>} flush>
            {data.recent.length ? <ActivityList items={data.recent} /> : <div className="empty">No activities yet</div>}
          </Card>
        </div>
      )}
    </>
  );
}
