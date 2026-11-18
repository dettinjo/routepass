import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CalendarHeatmap, GridHeatmap, HBars, Legend, LineChart, StackedBars } from "../components/charts";
import { RoutesMap } from "../components/maps";
import { Card, Empty, Seg, Skeleton, SportDot, Stat, Tabs } from "../components/ui";
import { api } from "../lib/api";
import { FAMILIES, FAMILY_LABEL, familyColor } from "../lib/colors";
import { duration, hours, int, km, num, speed } from "../lib/format";
import { FamilyChips, METRICS, metricFormat, type Metric } from "../components/shared";
import { SportIcon } from "../components/icons";

type Tab = "trends" | "calendar" | "fitness" | "records" | "power" | "habits" | "map";
const TABS: { value: Tab; label: string }[] = [
  { value: "trends", label: "Trends" },
  { value: "calendar", label: "Calendar" },
  { value: "fitness", label: "Fitness & form" },
  { value: "records", label: "Records" },
  { value: "power", label: "Power curve" },
  { value: "habits", label: "Habits" },
  { value: "map", label: "Route map" },
];
const YEAR_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)"];
type Range = "all" | "1y" | "90d" | "ytd";
function rangeStart(r: Range): string | undefined {
  const now = new Date();
  if (r === "1y") return new Date(now.getTime() - 365 * 86400000).toISOString().slice(0, 10);
  if (r === "90d") return new Date(now.getTime() - 90 * 86400000).toISOString().slice(0, 10);
  if (r === "ytd") return `${now.getFullYear()}-01-01`;
  return undefined;
}

function Trends({ families }: { families: string[] }) {
  const [grain, setGrain] = useState<"week" | "month" | "year">("month");
  const [metric, setMetric] = useState<Metric>("distance_m");
  const [range, setRange] = useState<Range>("all");
  const [cumMetric, setCumMetric] = useState<"distance_m" | "moving_time_s" | "elevation_m">("distance_m");
  const start = rangeStart(range);
  const ts = useQuery<any>({ queryKey: ["ts", grain, families, start], queryFn: () => api("/insights/timeseries", { params: { grain, family: families, start } }) });
  const totals = useQuery<any>({ queryKey: ["totals", families, start], queryFn: () => api("/insights/totals", { params: { family: families, start } }) });
  const cum = useQuery<Record<string, number[]>>({ queryKey: ["cum", families, cumMetric], queryFn: () => api("/insights/cumulative", { params: { family: families, metric: cumMetric } }) });

  const series = useMemo(() => FAMILIES.filter((f) => ts.data?.groups.includes(f)).map((f) => ({ key: f, label: FAMILY_LABEL[f], color: familyColor(f) })), [ts.data]);
  const bars = useMemo(() => (ts.data?.buckets || []).map((b: any) => ({
    label: grain === "year" ? b.start.slice(0, 4) : new Date(b.start).toLocaleDateString(undefined, grain === "month" ? { month: "short", year: "numeric" } : { day: "numeric", month: "short", year: "numeric" }),
    values: Object.fromEntries(Object.entries(b.groups).map(([k, v]: [string, any]) => [k, v[metric]])),
  })), [ts.data, grain, metric]);

  const cumChart = useMemo(() => {
    if (!cum.data) return null;
    const years = Object.keys(cum.data).slice(-5);
    if (!years.length) return null;
    const len = 366;
    const scale = cumMetric === "distance_m" ? 1000 : cumMetric === "moving_time_s" ? 3600 : 1;
    return {
      years,
      x: Array.from({ length: len }, (_, i) => i + 1),
      series: years.map((y, i) => ({
        label: y, color: YEAR_COLORS[years.length - 1 - i],
        values: Array.from({ length: len }, (_, d) => (cum.data![y][d] != null ? cum.data![y][d] / scale : null)),
        width: i === years.length - 1 ? 2.5 : 1.5,
      })),
    };
  }, [cum.data, cumMetric]);

  const t = totals.data?.totals;
  return (
    <div className="stack gap16">
      <div className="row between">
        <Seg value={range} options={[{ value: "all", label: "All time" }, { value: "1y", label: "12 months" }, { value: "ytd", label: "This year" }, { value: "90d", label: "90 days" }]} onChange={setRange} />
      </div>
      {t && (
        <Card>
          <div className="stats">
            <Stat label="Activities" value={int(t.count)} />
            <Stat label="Active days" value={int(t.active_days)} />
            <Stat label="Distance" value={km(t.distance_m, 0)} unit="km" />
            <Stat label="Moving time" value={hours(t.moving_time_s)} unit="h" />
            <Stat label="Elevation" value={int(t.elevation_m)} unit="m" />
            <Stat label="Training load" value={int(t.load)} />
            <Stat label="Work" value={int(t.work_kj)} unit="kJ" />
            <Stat label="Longest" value={km(t.longest_distance_m, 0)} unit="km" />
          </div>
        </Card>
      )}
      <Card title="Volume over time"
        actions={<><Seg value={grain} options={[{ value: "week", label: "Week" }, { value: "month", label: "Month" }, { value: "year", label: "Year" }]} onChange={setGrain} /><Seg value={metric} options={METRICS} onChange={setMetric} /></>}>
        {ts.isLoading ? <Skeleton h={260} /> : bars.length ? (
          <>
            <StackedBars data={bars} series={series} format={metricFormat(metric)} height={260} />
            {series.length > 1 && <div className="mt8"><Legend items={series} /></div>}
          </>
        ) : <Empty title="No data" />}
      </Card>
      <div className="grid g2">
        <Card title="Year over year" hint="Cumulative from 1 January"
          actions={<Seg value={cumMetric} options={[{ value: "distance_m", label: "km" }, { value: "moving_time_s", label: "hours" }, { value: "elevation_m", label: "elev." }]} onChange={setCumMetric} />}>
          {cumChart ? (
            <>
              <LineChart x={cumChart.x} series={cumChart.series} height={260}
                xFormat={(d) => new Date(2025, 0, d).toLocaleDateString(undefined, { day: "numeric", month: "short" })}
                yFormat={(v) => int(v)} />
              <div className="mt8"><Legend line items={cumChart.series.map((s) => ({ key: s.label, label: s.label, color: s.color }))} /></div>
            </>
          ) : <Skeleton h={260} />}
        </Card>
        <Card title="By sport" flush>
          {totals.data && (
            <div className="list">
              {totals.data.by_sport.map((s: any) => (
                <div key={s.sport} className="item" style={{ cursor: "default" }}>
                  <span className="sport-badge" style={{ width: 36, height: 36, background: `color-mix(in srgb, ${familyColor(s.family)} 16%, transparent)`, color: familyColor(s.family) }}>
                    <SportIcon sport={s.sport} family={s.family} size={19} />
                  </span>
                  <div className="main-col">
                    <span className="name small">{s.label} <span className="muted">· {int(s.count)}×</span></span>
                    <div className="metrics"><span>{km(s.distance_m, 0)} km</span><span>{hours(s.moving_time_s)} h</span><span>{int(s.elevation_m)} m</span><span className="extra">⌀ {km(s.count ? s.distance_m / s.count : 0)} km</span></div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function CalendarTab({ families }: { families: string[] }) {
  const nav = useNavigate();
  const [year, setYear] = useState(new Date().getFullYear());
  const [metric, setMetric] = useState<"distance_m" | "moving_time_s" | "elevation_m" | "load">("moving_time_s");
  const { data } = useQuery<any[]>({ queryKey: ["calendar", families, year], queryFn: () => api("/insights/calendar", { params: { family: families, start: `${year}-01-01`, end: `${year}-12-31` } }) });
  const ed = useQuery<any>({ queryKey: ["eddington", families], queryFn: () => api("/insights/eddington", { params: { family: families } }) });
  const days = useMemo(() => Object.fromEntries((data || []).map((d) => [d.date, d[metric]])), [data, metric]);
  const fmt = metricFormat(metric as Metric);
  const total = (data || []).reduce((s, d) => s + d[metric], 0);
  return (
    <div className="stack gap16">
      <Card title={`${year}`} hint={`${data?.length ?? 0} active days · ${fmt(total)}`}
        actions={<>
          <button className="sm" onClick={() => setYear(year - 1)}>←</button>
          <button className="sm" disabled={year >= new Date().getFullYear()} onClick={() => setYear(year + 1)}>→</button>
          <Seg value={metric} options={[{ value: "moving_time_s", label: "Time" }, { value: "distance_m", label: "Distance" }, { value: "elevation_m", label: "Elevation" }, { value: "load", label: "Load" }]} onChange={setMetric} />
        </>}>
        <CalendarHeatmap year={year} days={days} metric={METRICS.find((m) => m.value === metric)!.label} format={fmt}
          onDay={(d) => nav(`/activities?start=${d}&end=${d}`)} />
        <div className="row small muted mt8" style={{ gap: 4 }}>Less {["--seq-0", "--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5", "--seq-6"].map((v) => <i key={v} style={{ width: 11, height: 11, borderRadius: 2, background: `var(${v})`, display: "inline-block" }} />)} More</div>
      </Card>
      {ed.data && (
        <Card title="Eddington number" hint="The largest E such that you covered at least E km on E different days">
          <div className="stats">
            <Stat label="Eddington" value={ed.data.value} />
            <Stat label={`Days ≥ ${ed.data.next} km still needed`} value={ed.data.days_needed} />
          </div>
        </Card>
      )}
    </div>
  );
}

function Fitness({ families }: { families: string[] }) {
  const [days, setDays] = useState(365);
  const { data } = useQuery<any>({ queryKey: ["load", families, days], queryFn: () => api("/insights/load", { params: { family: families, days } }) });
  const chart = useMemo(() => {
    if (!data?.series.length) return null;
    const x = data.series.map((p: any) => new Date(p.date).getTime() / 1000);
    return {
      x,
      lines: [
        { label: "Fitness (CTL)", color: "var(--series-1)", values: data.series.map((p: any) => p.ctl), fill: true },
        { label: "Fatigue (ATL)", color: "var(--series-2)", values: data.series.map((p: any) => p.atl) },
      ],
      form: [{ label: "Form (TSB)", color: "var(--series-3)", values: data.series.map((p: any) => p.tsb), fill: true }],
      load: [{ label: "Daily load", color: "var(--series-7)", values: data.series.map((p: any) => p.load || null) }],
    };
  }, [data]);
  if (!data) return <Skeleton h={400} />;
  const c = data.current;
  const methods = data.methods as Record<string, number>;
  return (
    <div className="stack gap16">
      <Card title="Current" actions={<Seg value={String(days)} options={[{ value: "90", label: "90 d" }, { value: "180", label: "6 mo" }, { value: "365", label: "1 y" }, { value: "730", label: "2 y" }, { value: "1825", label: "5 y" }]} onChange={(v) => setDays(Number(v))} />}>
        {c && (
          <div className="stats">
            <Stat label="Fitness (CTL)" value={num(c.ctl, 0)} />
            <Stat label="Fatigue (ATL)" value={num(c.atl, 0)} />
            <Stat label="Form (TSB)" value={num(c.tsb, 0)} />
            <Stat label="7-day ramp" value={data.ramp_7d != null ? num(data.ramp_7d) : "–"} />
            <Stat label="Status" value={<span style={{ fontSize: 16, textTransform: "capitalize" }}>{data.status}</span>} />
          </div>
        )}
        <p className="small muted mt8" style={{ marginBottom: 0 }}>
          Load per activity: power TSS when FTP is set, heart-rate TSS when max HR is set, otherwise a duration estimate.
          In this window: {Object.entries(methods).map(([k, v]) => `${v} ${k}`).join(", ") || "none"}. <Link to="/settings">Set your profile</Link> for accurate numbers.
        </p>
      </Card>
      {chart && (
        <>
          <Card title="Fitness and fatigue">
            <LineChart x={chart.x} series={chart.lines} xTime height={260} syncKey="load" yFormat={(v) => v.toFixed(0)} />
            <div className="mt8"><Legend line items={chart.lines.map((l) => ({ key: l.label, label: l.label, color: l.color }))} /></div>
          </Card>
          <div className="grid g2">
            <Card title="Form" hint="Positive = fresh, −10 to −30 = productive training, below −30 = overreaching">
              <LineChart x={chart.x} series={chart.form} xTime height={180} syncKey="load" yFormat={(v) => v.toFixed(0)} />
            </Card>
            <Card title="Daily load">
              <LineChart x={chart.x} series={chart.load} xTime height={180} syncKey="load" yFormat={(v) => v.toFixed(0)} />
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

const DIST_LABEL: Record<number, string> = { 400: "400 m", 1000: "1 km", 1609: "1 mile", 5000: "5 km", 10000: "10 km", 20000: "20 km", 21097: "Half marathon", 40000: "40 km", 42195: "Marathon", 50000: "50 km", 100000: "100 km", 160934: "100 miles" };

function Records({ families }: { families: string[] }) {
  const [range, setRange] = useState<Range>("all");
  const start = rangeStart(range);
  const { data } = useQuery<any>({ queryKey: ["records", families, start], queryFn: () => api("/insights/records", { params: { family: families, start } }) });
  if (!data) return <Skeleton h={400} />;
  const Ref = ({ a }: { a: any }) => <Link to={`/activities/${a.id}`} className="small">{a.name} · {a.date}</Link>;
  return (
    <div className="stack gap16">
      <Seg value={range} options={[{ value: "all", label: "All time" }, { value: "1y", label: "12 months" }, { value: "ytd", label: "This year" }, { value: "90d", label: "90 days" }]} onChange={setRange} />
      {Object.keys(data).length === 0 && <Empty title="No records yet" />}
      <div className="grid g2">
        {FAMILIES.filter((f) => data[f]).map((f) => {
          const r = data[f];
          const rows: [string, string, any][] = [];
          if (r.longest) rows.push(["Longest", `${km(r.longest.value)} km`, r.longest.activity]);
          if (r.longest_time) rows.push(["Longest time", duration(r.longest_time.value), r.longest_time.activity]);
          if (r.most_elevation) rows.push(["Most climbing", `${int(r.most_elevation.value)} m`, r.most_elevation.activity]);
          if (r.biggest_climb) rows.push(["Biggest single climb", `${int(r.biggest_climb.value)} m`, r.biggest_climb.activity]);
          if (r.fastest_avg) rows.push(["Fastest average", speed(r.fastest_avg.value, f), r.fastest_avg.activity]);
          if (r.highest_power) rows.push(["Best normalized power", `${int(r.highest_power.value)} W`, r.highest_power.activity]);
          if (r.biggest_load) rows.push(["Biggest load", int(r.biggest_load.value), r.biggest_load.activity]);
          for (const b of r.best_times || []) rows.push([`Best ${DIST_LABEL[b.distance_m] ?? b.distance_m + " m"}`, `${duration(b.time_s, true)} (${speed(b.distance_m / b.time_s, f)})`, b.activity]);
          return (
            <Card key={f} title={<span className="row"><SportDot family={f} />{FAMILY_LABEL[f]}</span>} flush>
              <div className="table-wrap"><table><tbody>
                {rows.map(([label, value, a]) => (
                  <tr key={label}><td className="secondary">{label}</td><td className="r" style={{ fontWeight: 600 }}>{value}</td><td><Ref a={a} /></td></tr>
                ))}
              </tbody></table></div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function PowerTab() {
  const year = new Date().getFullYear();
  const all = useQuery<any[]>({ queryKey: ["pc", "all"], queryFn: () => api("/insights/power-curve") });
  const cur = useQuery<any[]>({ queryKey: ["pc", "90"], queryFn: () => api("/insights/power-curve", { params: { start: rangeStart("90d") } }) });
  const thisYear = useQuery<any[]>({ queryKey: ["pc", year], queryFn: () => api("/insights/power-curve", { params: { start: `${year}-01-01` } }) });
  if (!all.data) return <Skeleton h={300} />;
  if (!all.data.length) return <Empty title="No power data">Power curves need activities recorded with a power meter.</Empty>;
  const secs = all.data.map((p) => p.seconds);
  const pick = (d?: any[]) => secs.map((s) => d?.find((p) => p.seconds === s)?.watts ?? null);
  const lines = [
    { label: "All time", color: "var(--series-1)", values: pick(all.data) },
    { label: String(year), color: "var(--series-2)", values: pick(thisYear.data) },
    { label: "Last 90 days", color: "var(--series-3)", values: pick(cur.data) },
  ];
  const lbl = (s: number) => (s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s / 60)}m` : `${s / 3600}h`);
  return (
    <div className="stack gap16">
      <Card title="Mean-maximal power">
        <LineChart x={secs} series={lines} logX height={300} xFormat={lbl} yFormat={(v) => `${v.toFixed(0)} W`} />
        <div className="mt8"><Legend line items={lines.map((l) => ({ key: l.label, label: l.label, color: l.color }))} /></div>
      </Card>
      <Card title="Best efforts" flush>
        <div className="table-wrap"><table>
          <thead><tr><th>Duration</th><th className="r">All time</th><th>Activity</th><th className="r">{year}</th><th className="r">90 days</th></tr></thead>
          <tbody>{all.data.map((p, i) => (
            <tr key={p.seconds}><td>{lbl(p.seconds)}</td><td className="r" style={{ fontWeight: 600 }}>{int(p.watts)} W</td>
              <td><Link to={`/activities/${p.activity.id}`} className="small">{p.activity.name} · {p.activity.date}</Link></td>
              <td className="r">{int(lines[1].values[i])}</td><td className="r">{int(lines[2].values[i])}</td></tr>
          ))}</tbody>
        </table></div>
      </Card>
    </div>
  );
}

function Habits({ families }: { families: string[] }) {
  const { data } = useQuery<any>({ queryKey: ["habits", families], queryFn: () => api("/insights/habits", { params: { family: families } }) });
  if (!data) return <Skeleton h={300} />;
  const wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return (
    <div className="stack gap16">
      <Card title="When you train" hint="Activity starts by weekday and hour (local time)">
        <GridHeatmap grid={data.weekday_hour} />
      </Card>
      <div className="grid g3">
        <Card title="By weekday" hint="Moving time">
          <HBars format={(v) => `${hours(v)} h`} rows={data.by_weekday.map((t: any, i: number) => ({ label: wd[i], value: t.moving_time_s }))} />
        </Card>
        <Card title="Distance distribution" hint="Number of activities">
          <HBars format={(v) => int(v)} rows={data.distance_histogram.map((b: any) => ({ label: `${b.bucket} km`, value: b.count }))} />
        </Card>
        <Card title="Streaks">
          <div className="stats" style={{ gridTemplateColumns: "repeat(2, minmax(0,1fr))" }}>
            <Stat label="Current days" value={data.streaks.current_days} />
            <Stat label="Longest days" value={data.streaks.longest_days} />
            <Stat label="Current weeks" value={data.streaks.current_weeks} />
            <Stat label="Longest weeks" value={data.streaks.longest_weeks} />
          </div>
        </Card>
      </div>
    </div>
  );
}

function MapTab({ families }: { families: string[] }) {
  const nav = useNavigate();
  const [range, setRange] = useState<Range>("1y");
  const start = rangeStart(range);
  const { data } = useQuery<any[]>({ queryKey: ["heatmap", families, start], queryFn: () => api("/insights/heatmap", { params: { family: families, start } }) });
  const onSelect = useCallback((id: number) => nav(`/activities/${id}`), [nav]);
  return (
    <Card title="Everywhere you've been" hint={data ? `${data.length} routes — overlapping roads build up; click a line to open it` : undefined}
      actions={<Seg value={range} options={[{ value: "all", label: "All time" }, { value: "1y", label: "12 months" }, { value: "ytd", label: "This year" }, { value: "90d", label: "90 days" }]} onChange={setRange} />}>
      {data ? <RoutesMap routes={data} onSelect={onSelect} /> : <Skeleton h={560} />}
    </Card>
  );
}

export default function Insights() {
  const { tab = "trends" } = useParams();
  const nav = useNavigate();
  const [families, setFamilies] = useState<string[]>([]);
  const t = tab as Tab;
  return (
    <>
      <div className="page-head">
        <div><h1>Insights</h1><div className="sub">Computed over deduplicated activities — nothing counts twice</div></div>
        {t !== "power" && <FamilyChips value={families} onChange={setFamilies} />}
      </div>
      <Tabs value={t} tabs={TABS} onChange={(v) => nav(`/insights/${v}`)} />
      {t === "trends" && <Trends families={families} />}
      {t === "calendar" && <CalendarTab families={families} />}
      {t === "fitness" && <Fitness families={families} />}
      {t === "records" && <Records families={families} />}
      {t === "power" && <PowerTab />}
      {t === "habits" && <Habits families={families} />}
      {t === "map" && <MapTab families={families} />}
    </>
  );
}
