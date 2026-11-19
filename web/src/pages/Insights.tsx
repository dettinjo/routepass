import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState, type ComponentType } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { CalendarHeatmap, GridHeatmap, HBars, HeatLegend, Legend, LineChart, StackedBars } from "../components/charts";
import { DataQualityNote } from "../components/DataQuality";
import { RoutesMap } from "../components/maps";
import { GearTab, TilesTab, ZonesTab } from "../components/InsightsExtras";
import {
  ICON, IconCalendarStat, IconCheck, IconChevronDownSm, IconFilter, IconFitness, IconGear, IconLeft, IconMap, IconOverview,
  IconPerformance, IconPlaces, IconRight, IconTime, IconTrophy, MetricIcon, SportIcon,
} from "../components/icons";
import { Card, Empty, Modal, Seg, SegSelect, Skeleton, Stat, Tabs } from "../components/ui";
import { api } from "../lib/api";
import { FAMILIES, FAMILY_LABEL, familyColor, heatScale, yearColor } from "../lib/colors";
import { duration, hours, int, km, num, speed } from "../lib/format";
import { FamilyChips, METRICS, metricFormat, type Metric } from "../components/shared";

type Tab = "trends" | "calendar" | "habits" | "fitness" | "zones" | "records" | "power" | "map" | "tiles" | "gear";
type Group = "overview" | "performance" | "places" | "gear";
type Range = "all" | "1y" | "ytd" | "90d";

const GROUPS: { value: Group; label: string; icon: ComponentType<{ size?: number }>; tabs: { value: Tab; label: string }[] }[] = [
  { value: "overview", label: "Overview", icon: IconOverview, tabs: [{ value: "trends", label: "Trends" }, { value: "calendar", label: "Calendar" }, { value: "habits", label: "Habits" }] },
  { value: "performance", label: "Performance", icon: IconPerformance, tabs: [{ value: "fitness", label: "Fitness & form" }, { value: "zones", label: "Zones" }, { value: "records", label: "Records" }, { value: "power", label: "Power" }] },
  { value: "places", label: "Places", icon: IconPlaces, tabs: [{ value: "map", label: "Route map" }, { value: "tiles", label: "Explorer tiles" }] },
  { value: "gear", label: "Gear", icon: IconGear, tabs: [{ value: "gear", label: "Gear" }] },
];
const groupOf = (t: Tab) => GROUPS.find((g) => g.tabs.some((x) => x.value === t))!;
/** Which shared filters a tab honours — controls that would do nothing are hidden. */
const USES_RANGE = new Set<Tab>(["trends", "habits", "fitness", "zones", "records", "map", "tiles", "gear"]);
const USES_SPORT = new Set<Tab>(["trends", "calendar", "habits", "fitness", "zones", "records", "map", "tiles", "gear"]);
const SHORT_RANGE: Record<Range, string> = { all: "All time", "1y": "12 months", ytd: "This year", "90d": "90 days" };
const RANGES: { value: Range; label: string }[] = [{ value: "all", label: "All time" }, { value: "1y", label: "12 months" }, { value: "ytd", label: "This year" }, { value: "90d", label: "90 days" }];

function rangeStart(r: Range): string | undefined {
  const now = new Date();
  if (r === "1y") return new Date(now.getTime() - 365 * 86400000).toISOString().slice(0, 10);
  if (r === "90d") return new Date(now.getTime() - 90 * 86400000).toISOString().slice(0, 10);
  if (r === "ytd") return `${now.getFullYear()}-01-01`;
  return undefined;
}
function rangeDays(r: Range): number {
  if (r === "90d") return 90;
  if (r === "1y") return 365;
  if (r === "ytd") return Math.max(30, Math.ceil((Date.now() - new Date(new Date().getFullYear(), 0, 1).getTime()) / 86400000));
  return 1825;
}
interface F { families: string[]; range: Range; start?: string }

/** Heat colour follows the selected sport; with several sports it is neutral ink. */
const heatFor = (families: string[]) => heatScale(families.length === 1 ? familyColor(families[0]) : undefined);

function Trends({ families, range, start }: F) {
  const [grain, setGrain] = useState<"week" | "month" | "year">(range === "90d" ? "week" : "month");
  const [metric, setMetric] = useState<Metric>("distance_m");
  const [cumMetric, setCumMetric] = useState<"distance_m" | "moving_time_s" | "elevation_m">("distance_m");
  const [allSports, setAllSports] = useState(false);
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
    const scale = cumMetric === "distance_m" ? 1000 : cumMetric === "moving_time_s" ? 3600 : 1;
    return {
      x: Array.from({ length: 366 }, (_, i) => i + 1),
      series: years.map((y, i) => {
        const fromNewest = years.length - 1 - i;
        return {
          label: y, color: yearColor(fromNewest),
          values: Array.from({ length: 366 }, (_, d) => (cum.data![y][d] != null ? cum.data![y][d] / scale : null)),
          width: fromNewest === 0 ? 2.6 : 1.5,
        };
      }),
    };
  }, [cum.data, cumMetric]);

  const t = totals.data?.totals;
  const bySport: any[] = totals.data?.by_sport || [];
  const sports = allSports ? bySport : bySport.slice(0, 6);
  return (
    <div className="stack gap16">
      {t && (
        <Card>
          <div className="stats">
            <Stat icon="count" label="Activities" value={int(t.count)} />
            <Stat icon="days" label="Active days" value={int(t.active_days)} />
            <Stat icon="distance" label="Distance" value={km(t.distance_m, 0)} unit="km" />
            <Stat icon="time" label="Moving time" value={hours(t.moving_time_s)} unit="h" />
            <Stat icon="elevation" label="Climbing" value={int(t.elevation_m)} unit="m" />
            {t.load > 0 && <Stat icon="load" label="Training load" value={int(t.load)} info="Sum of per-activity load (TSS scale)." />}
            {t.work_kj > 0 && <Stat icon="power" label="Work" value={int(t.work_kj)} unit="kJ" />}
            {t.longest_distance_m > 0 && <Stat icon="climb" label="Longest" value={km(t.longest_distance_m, 0)} unit="km" />}
          </div>
        </Card>
      )}
      <Card title="Volume over time" icon={MetricIcon.count}
        actions={<><Seg value={grain} options={[{ value: "week", label: "Week" }, { value: "month", label: "Month" }, { value: "year", label: "Year" }]} onChange={setGrain} /><SegSelect label="Metric" value={metric} options={METRICS} onChange={setMetric} /></>}>
        {ts.isLoading ? <Skeleton h={260} /> : bars.length ? (
          <>
            <StackedBars data={bars} series={series} format={metricFormat(metric)} height={260} />
            {series.length > 1 && <div className="mt8"><Legend items={series} /></div>}
          </>
        ) : <Empty title="No activities in this range" />}
      </Card>
      <div className="grid g2">
        <Card title="By sport" icon={MetricIcon.count} flush>
          {totals.data ? (
            <>
              <div className="list">
                {sports.map((s: any) => (
                  <div key={s.sport} className="item" style={{ cursor: "default" }}>
                    <span className="sport-badge" style={{ width: 36, height: 36, background: `color-mix(in srgb, ${familyColor(s.family)} 16%, transparent)`, color: familyColor(s.family) }}>
                      <SportIcon sport={s.sport} family={s.family} size={ICON.header} />
                    </span>
                    <div className="main-col">
                      <span className="name small">{s.label} <span className="muted">· {int(s.count)}×</span></span>
                      <div className="metrics">
                        {s.distance_m > 0 && <span>{km(s.distance_m, 0)} km</span>}
                        <span>{hours(s.moving_time_s)} h</span>
                        {s.elevation_m > 0 && <span>{int(s.elevation_m)} m</span>}
                        {s.distance_m > 0 && <span className="extra">⌀ {km(s.count ? s.distance_m / s.count : 0)} km</span>}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              {bySport.length > 6 && (
                <div className="by-sport-more"><button className="sm ghost" onClick={() => setAllSports(!allSports)}>{allSports ? "Show fewer" : `Show all ${bySport.length} sports`}</button></div>
              )}
            </>
          ) : <Skeleton h={260} />}
        </Card>
        <Card title="Year over year" icon={IconCalendarStat} hint="Cumulative from 1 January — this year in blue"
          actions={<Seg value={cumMetric} options={[{ value: "distance_m", label: "km" }, { value: "moving_time_s", label: "hours" }, { value: "elevation_m", label: "climb" }]} onChange={setCumMetric} />}>
          {cumChart ? (
            <>
              <LineChart x={cumChart.x} series={cumChart.series} height={280}
                xFormat={(d) => new Date(2025, 0, d).toLocaleDateString(undefined, { day: "numeric", month: "short" })}
                yFormat={(v) => int(v)} />
              <div className="mt8"><Legend line items={[...cumChart.series].reverse().map((s) => ({ key: s.label, label: s.label, color: s.color }))} /></div>
            </>
          ) : <Skeleton h={280} />}
        </Card>
      </div>
    </div>
  );
}

function CalendarTab({ families }: F) {
  const nav = useNavigate();
  const [year, setYear] = useState(new Date().getFullYear());
  const [metric, setMetric] = useState<"distance_m" | "moving_time_s" | "elevation_m" | "load">("moving_time_s");
  const { data } = useQuery<any[]>({ queryKey: ["calendar", families, year], queryFn: () => api("/insights/calendar", { params: { family: families, start: `${year}-01-01`, end: `${year}-12-31` } }) });
  const ed = useQuery<any>({ queryKey: ["eddington", families], queryFn: () => api("/insights/eddington", { params: { family: families } }) });
  const days = useMemo(() => Object.fromEntries((data || []).map((d) => [d.date, d[metric]])), [data, metric]);
  const fmt = metricFormat(metric as Metric);
  const total = (data || []).reduce((s, d) => s + d[metric], 0);
  const scale = heatFor(families);
  return (
    <div className="stack gap16">
      <Card icon={IconCalendarStat} hint={`${data?.length ?? 0} active days · ${fmt(total)}`}
        title={<span className="row nowrap" style={{ gap: 2 }}>
          <button className="ghost icon sm" aria-label="Previous year" onClick={() => setYear(year - 1)}><IconLeft size={ICON.button} /></button>
          {year}
          <button className="ghost icon sm" aria-label="Next year" disabled={year >= new Date().getFullYear()} onClick={() => setYear(year + 1)}><IconRight size={ICON.button} /></button>
        </span>}
        actions={<SegSelect label="Metric" value={metric} options={[{ value: "moving_time_s", label: "Time" }, { value: "distance_m", label: "Distance" }, { value: "elevation_m", label: "Climbing" }, { value: "load", label: "Load" }]} onChange={setMetric} />}>
        <CalendarHeatmap year={year} days={days} metric={METRICS.find((m) => m.value === metric)!.label} format={fmt} scale={scale}
          onDay={(d) => nav(`/activities?start=${d}&end=${d}`)} />
        <div className="mt8"><HeatLegend scale={scale} /></div>
      </Card>
      {ed.data && (
        <Card title="Eddington number" icon={IconTrophy} info="The largest E such that you covered at least E km on E different days.">
          <div className="stats">
            <Stat label="Eddington" value={ed.data.value} />
            <Stat label={`Days ≥ ${ed.data.next} km still needed`} value={ed.data.days_needed} />
          </div>
        </Card>
      )}
    </div>
  );
}

function Fitness({ families, range }: F) {
  const days = rangeDays(range);
  const { data } = useQuery<any>({ queryKey: ["load", families, days], queryFn: () => api("/insights/load", { params: { family: families, days } }) });
  const chart = useMemo(() => {
    if (!data?.series.length) return null;
    const x = data.series.map((p: any) => new Date(p.date).getTime() / 1000);
    return {
      x,
      // Ink lines: fitness solid, fatigue quiet — neither may look like a sport.
      lines: [
        { label: "Fitness (CTL)", color: "var(--line-1)", values: data.series.map((p: any) => p.ctl), fill: true, width: 2.2 },
        { label: "Fatigue (ATL)", color: "var(--line-2)", values: data.series.map((p: any) => p.atl), width: 1.5 },
      ],
      form: [{ label: "Form (TSB)", color: "var(--line-1)", values: data.series.map((p: any) => p.tsb) }],
      load: [{ label: "Daily load", color: "var(--text-secondary)", values: data.series.map((p: any) => p.load ?? 0) }],
    };
  }, [data]);
  if (!data) return <Skeleton h={400} />;
  const c = data.current;
  return (
    <div className="stack gap16">
      <Card title="Now" icon={IconFitness}>
        {c && (
          <div className="stats">
            <Stat label="Fitness" value={num(c.ctl, 0)} info="CTL: your average daily load over about six weeks." />
            <Stat label="Fatigue" value={num(c.atl, 0)} info="ATL: your average daily load over about one week." />
            <Stat label="Form" value={num(c.tsb, 0)} info="TSB = fitness − fatigue. Positive is fresh; −10 to −30 is productive training; below −30 is overreaching." />
            <Stat label="7-day ramp" value={data.ramp_7d != null ? num(data.ramp_7d) : "–"} info="How much fitness changed over the last week." />
            <Stat label="Status" value={<span style={{ fontSize: 16, textTransform: "capitalize" }}>{data.status}</span>} />
          </div>
        )}
      </Card>
      {chart && (
        <>
          <Card title="Fitness and fatigue" icon={IconFitness}>
            <LineChart x={chart.x} series={chart.lines} xTime height={260} syncKey="load" yFormat={(v) => v.toFixed(0)} />
            <div className="mt8"><Legend line items={chart.lines.map((l) => ({ key: l.label, label: l.label, color: l.color }))} /></div>
          </Card>
          <div className="grid g2">
            <Card title="Form" icon={IconFitness} hint="Shaded: fresh (above 5) · productive (−10 to −30) · overreaching (below −30)">
              <LineChart x={chart.x} series={chart.form} xTime height={190} syncKey="load" yFormat={(v) => v.toFixed(0)}
                bands={[{ from: 5, to: null, color: "--accent", alpha: "1a" }, { from: -30, to: -10, color: "--good", alpha: "1a" }, { from: null, to: -30, color: "--warn", alpha: "24" }]} />
            </Card>
            <Card title="Daily load" icon={MetricIcon.load}>
              <LineChart x={chart.x} series={chart.load} xTime height={190} syncKey="load" yFormat={(v) => v.toFixed(0)} />
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

const DIST_LABEL: Record<number, string> = { 400: "400 m", 1000: "1 km", 1609: "1 mile", 5000: "5 km", 10000: "10 km", 20000: "20 km", 21097: "Half marathon", 40000: "40 km", 42195: "Marathon", 50000: "50 km", 100000: "100 km", 160934: "100 miles" };

function Records({ families, start }: F) {
  const { data } = useQuery<any>({ queryKey: ["records", families, start], queryFn: () => api("/insights/records", { params: { family: families, start } }) });
  if (!data) return <Skeleton h={400} />;
  const Ref = ({ a }: { a: any }) => <Link to={`/activities/${a.id}`} className="small">{a.name} · {a.date}</Link>;
  if (Object.keys(data).length === 0) return <Empty title="No records in this range" icon={IconTrophy} />;
  return (
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
          <Card key={f} title={<span className="row nowrap"><SportIcon family={f} size={ICON.header} style={{ color: familyColor(f) }} />{FAMILY_LABEL[f]}</span>} flush>
            <div className="table-wrap"><table><tbody>
              {rows.map(([label, value, a]) => (
                <tr key={label}><td className="secondary">{label}</td><td className="r" style={{ fontWeight: 600 }}>{value}</td><td><Ref a={a} /></td></tr>
              ))}
            </tbody></table></div>
          </Card>
        );
      })}
    </div>
  );
}

function PowerTab() {
  const year = new Date().getFullYear();
  const all = useQuery<any[]>({ queryKey: ["pc", "all"], queryFn: () => api("/insights/power-curve") });
  const cur = useQuery<any[]>({ queryKey: ["pc", "90"], queryFn: () => api("/insights/power-curve", { params: { start: rangeStart("90d") } }) });
  const thisYear = useQuery<any[]>({ queryKey: ["pc", year], queryFn: () => api("/insights/power-curve", { params: { start: `${year}-01-01` } }) });
  if (!all.data) return <Skeleton h={300} />;
  if (!all.data.length) return <Empty title="No power data" icon={MetricIcon.power}>Power curves need activities recorded with a power meter.</Empty>;
  const secs = all.data.map((p) => p.seconds);
  const pick = (d?: any[]) => secs.map((s) => d?.find((p) => p.seconds === s)?.watts ?? null);
  // Same time-comparison language as year over year: the newest period is the accent.
  const lines = [
    { label: "All time", color: "var(--year-2)", values: pick(all.data), width: 1.5 },
    { label: String(year), color: "var(--year-4)", values: pick(thisYear.data), width: 1.8 },
    { label: "Last 90 days", color: "var(--accent)", values: pick(cur.data), width: 2.4 },
  ];
  const lbl = (s: number) => (s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s / 60)}m` : `${s / 3600}h`);
  return (
    <div className="stack gap16">
      <Card title="Mean-maximal power" icon={MetricIcon.power} info="Your best average power for every duration.">
        <LineChart x={secs} series={lines} logX height={300} xFormat={lbl} yFormat={(v) => `${v.toFixed(0)} W`} />
        <div className="mt8"><Legend line items={lines.map((l) => ({ key: l.label, label: l.label, color: l.color }))} /></div>
      </Card>
      <Card title="Best efforts" icon={IconTrophy} flush>
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

function Habits({ families, start }: F) {
  const { data } = useQuery<any>({ queryKey: ["habits", families, start], queryFn: () => api("/insights/habits", { params: { family: families, start } }) });
  if (!data) return <Skeleton h={300} />;
  const wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const color = families.length === 1 ? familyColor(families[0]) : undefined;
  return (
    <div className="stack gap16">
      <Card title="When you train" icon={IconTime} hint="Activity starts by weekday and hour (local time)">
        <GridHeatmap grid={data.weekday_hour} scale={heatFor(families)} />
      </Card>
      <div className="grid g3">
        <Card title="By weekday" icon={IconCalendarStat} hint="Moving time">
          <HBars color={color} format={(v) => `${hours(v)} h`} rows={data.by_weekday.map((t: any, i: number) => ({ label: wd[i], value: t.moving_time_s }))} />
        </Card>
        <Card title="Distance distribution" icon={MetricIcon.distance} hint="Number of activities">
          <HBars color={color} format={(v) => int(v)} rows={data.distance_histogram.map((b: any) => ({ label: `${b.bucket} km`, value: b.count }))} />
        </Card>
        <Card title="Streaks" icon={MetricIcon.load}>
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

function MapTab({ families, start }: F) {
  const nav = useNavigate();
  const { data } = useQuery<any[]>({ queryKey: ["heatmap", families, start], queryFn: () => api("/insights/heatmap", { params: { family: families, start } }) });
  const onSelect = useCallback((id: number) => nav(`/activities/${id}`), [nav]);
  return (
    <Card title="Everywhere you've been" icon={IconMap} hint={data ? `${data.length} routes — overlapping roads build up; tap a line to open it` : undefined}>
      {data ? <RoutesMap routes={data} onSelect={onSelect} /> : <Skeleton h={560} />}
    </Card>
  );
}

export default function Insights() {
  const { tab: raw = "trends" } = useParams();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const tab = (GROUPS.some((g) => g.tabs.some((t) => t.value === raw)) ? raw : "trends") as Tab;
  const group = groupOf(tab);
  // Filters live in the URL so they survive tab switches, reloads and shared links.
  const families = (sp.get("sport") || "").split(",").filter(Boolean);
  const range = (RANGES.some((r) => r.value === sp.get("range")) ? sp.get("range") : "all") as Range;
  const setParam = (k: string, v: string) => {
    const n = new URLSearchParams(sp);
    if (v) n.set(k, v); else n.delete(k);
    setSp(n, { replace: true });
  };
  const go = (t: Tab) => nav(`/insights/${t}${sp.toString() ? `?${sp}` : ""}`);
  const f: F = { families, range, start: rangeStart(range) };
  const showSport = USES_SPORT.has(tab);
  const showRange = USES_RANGE.has(tab);
  const [sheet, setSheet] = useState<"view" | "filter" | null>(null);
  const tabLabel = group.tabs.find((t) => t.value === tab)!.label;
  const filtered = (showSport && families.length > 0) || (showRange && range !== "all");
  const filterSummary = [
    showSport ? (families.length === 0 ? "All sports" : families.length === 1 ? FAMILY_LABEL[families[0]] : `${families.length} sports`) : null,
    showRange ? SHORT_RANGE[range] : null,
  ].filter(Boolean).join(" · ");
  return (
    <>
      <div className="page-head">
        <div><h1>Insights</h1><div className="sub static">Computed over deduplicated activities — nothing counts twice</div></div>
      </div>
      {/* Phone: one row — the view you are on, and a summary of the filters. Each opens a sheet. */}
      <div className="viewbar hide-desktop">
        <button className="view" onClick={() => setSheet("view")} aria-label={`View: ${tabLabel}. Change view`}>
          <group.icon size={ICON.button} /><span>{tabLabel}</span><IconChevronDownSm size={ICON.button} />
        </button>
        {(showSport || showRange) && (
          <button className={`filter ${filtered ? "on" : ""}`} onClick={() => setSheet("filter")} aria-label={`Filters: ${filterSummary}`}>
            <IconFilter size={ICON.button} /><span>{filterSummary}</span>
          </button>
        )}
      </div>
      {sheet === "view" && (
        <Modal title="Insights" onClose={() => setSheet(null)}>
          {GROUPS.map((g) => (
            <div key={g.value} className="stack" style={{ gap: 4 }}>
              <span className="section-label row nowrap" style={{ gap: 6 }}><g.icon size={ICON.inline} />{g.label}</span>
              <div className="view-list">
                {g.tabs.map((t) => (
                  <button key={t.value} className={t.value === tab ? "on" : ""} onClick={() => { setSheet(null); go(t.value); }}>
                    {t.label}{t.value === tab && <IconCheck size={ICON.button} className="check" />}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </Modal>
      )}
      {sheet === "filter" && (
        <Modal title="Filter" onClose={() => setSheet(null)}
          footer={<><button onClick={() => { const n = new URLSearchParams(sp); n.delete("sport"); n.delete("range"); setSp(n, { replace: true }); }}>Reset</button><button className="primary" onClick={() => setSheet(null)}>Done</button></>}>
          {showSport && (
            <div className="stack" style={{ gap: 8 }}>
              <span className="section-label">Sports</span>
              <FamilyChips wrap value={families} onChange={(v) => setParam("sport", v.join(","))} />
            </div>
          )}
          {showRange && (
            <div className="stack" style={{ gap: 8 }}>
              <span className="section-label">Period</span>
              <Seg block value={range} options={RANGES} onChange={(v) => setParam("range", v === "all" ? "" : v)} />
            </div>
          )}
        </Modal>
      )}

      {/* Desktop: sections and sub-views on one row, filters on the next. */}
      <div className="hide-mobile">
        <div className="navrow">
          <Tabs value={group.value} onChange={(g) => go(GROUPS.find((x) => x.value === g)!.tabs[0].value)}
            tabs={GROUPS.map((g) => ({ value: g.value, label: <><g.icon size={ICON.button} />{g.label}</> }))} />
          {group.tabs.length > 1 && <Seg value={tab} options={group.tabs} onChange={go} />}
        </div>
        {(showSport || showRange) && (
          <div className="filterbar">
            {showSport && <FamilyChips value={families} onChange={(v) => setParam("sport", v.join(","))} />}
            {showRange && <Seg value={range} options={RANGES} onChange={(v) => setParam("range", v === "all" ? "" : v)} />}
          </div>
        )}
      </div>
      {group.value === "performance" && tab !== "records" && <div style={{ marginBottom: 16 }}><DataQualityNote /></div>}
      {tab === "trends" && <Trends {...f} />}
      {tab === "calendar" && <CalendarTab {...f} />}
      {tab === "habits" && <Habits {...f} />}
      {tab === "fitness" && <Fitness {...f} />}
      {tab === "zones" && <ZonesTab families={families} start={f.start} />}
      {tab === "records" && <Records {...f} />}
      {tab === "power" && <PowerTab />}
      {tab === "map" && <MapTab {...f} />}
      {tab === "tiles" && <TilesTab families={families} start={f.start} />}
      {tab === "gear" && <GearTab families={families} start={f.start} />}
    </>
  );
}
