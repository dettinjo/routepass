import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Legend, LineChart, StackedBars } from "../components/charts";
import { BrandIcon, IconArrowRight, IconCheck, IconList, IconSparkles, IconSync, IconTimeline, IconTrophy, MetricIcon } from "../components/icons";
import { ActivityList, FamilyChips, METRICS, metricFormat, type Metric } from "../components/shared";
import { Card, Seg, Skeleton, Stat } from "../components/ui";
import { api } from "../lib/api";
import { FAMILIES, FAMILY_LABEL, familyColor } from "../lib/colors";
import { ago, duration, int, km, pctDelta } from "../lib/format";
import { useStatus } from "../lib/hooks";
import type { Totals } from "../lib/types";

export { ActivityList, FamilyChips, METRICS, metricFormat, type Metric };

type Period = "week" | "month" | "year";
const FORM_TEXT: Record<string, [string, string]> = {
  fresh: ["good", "Rested — a good moment for a hard effort or a race."],
  transition: ["info", "Very rested; fitness slowly drops without training."],
  neutral: ["", "Balanced load — maintaining fitness."],
  productive: ["info", "Training is building fitness. Keep recovery in mind."],
  overreaching: ["bad", "Fatigue is high — plan easier days."],
};

function SetupCard({ strava, komoot }: { strava: boolean; komoot: boolean }) {
  const steps = [
    { done: strava, label: <>Connect <b>Strava</b></>, icon: "strava" },
    { done: komoot, label: <>Connect <b>Komoot</b></>, icon: "komoot" },
    { done: false, label: <>Choose what to sync, or bring everything up to date once</> },
  ];
  return (
    <Card title="Get started" icon={IconSparkles} hint="Three steps to one clean activity history">
      <div className="steps">
        {steps.map((s, i) => (
          <div key={i} className={`step ${s.done ? "done" : ""}`}>
            <span className="n">{s.done ? <IconCheck size={16} /> : i + 1}</span>
            {s.icon && <BrandIcon provider={s.icon} size={18} />}
            <span className="grow">{s.label}</span>
          </div>
        ))}
      </div>
      <div className="row mt16">
        <Link to={strava && komoot ? "/sync" : "/settings"} className="btn primary" style={{ background: "var(--accent)", color: "var(--accent-ink)", borderColor: "var(--accent)" }}>
          {strava && komoot ? "Set up sync" : "Connect accounts"}<IconArrowRight size={16} />
        </Link>
      </div>
    </Card>
  );
}

function PeriodCard({ periods }: { periods: Record<Period, { current: Totals; previous: Totals }> }) {
  const [p, setP] = useState<Period>("week");
  const { current: c, previous: v } = periods[p];
  return (
    <Card title="Your training" icon={IconTimeline} hint="Compared with the same span of the previous period"
      actions={<Seg value={p} options={[{ value: "week", label: "Week" }, { value: "month", label: "Month" }, { value: "year", label: "Year" }]} onChange={setP} />}>
      <div className="stats">
        <Stat icon="distance" label="Distance" value={km(c.distance_m, 0)} unit="km" delta={pctDelta(c.distance_m, v.distance_m)} />
        <Stat icon="time" label="Moving time" value={duration(c.moving_time_s)} delta={pctDelta(c.moving_time_s, v.moving_time_s)} />
        <Stat icon="elevation" label="Climbing" value={int(c.elevation_m)} unit="m" delta={pctDelta(c.elevation_m, v.elevation_m)} />
        <Stat icon="count" label="Activities" value={c.count} delta={pctDelta(c.count, v.count)} />
      </div>
    </Card>
  );
}

export default function Dashboard() {
  const nav = useNavigate();
  const [families, setFamilies] = useState<string[]>([]);
  const [metric, setMetric] = useState<Metric>("distance_m");
  const { data: status } = useStatus();
  const { data, isLoading } = useQuery<any>({
    queryKey: ["dashboard", families],
    queryFn: () => api("/insights/dashboard", { params: { family: families } }),
  });

  const weekly = useMemo(() => {
    if (!data) return null;
    const groups: string[] = data.weekly.groups;
    const buckets = data.weekly.buckets.slice(-26);
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
        { label: "Fitness", color: "var(--series-1)", values: load.series.map((p: any) => p.ctl), fill: true },
        { label: "Fatigue", color: "var(--series-2)", values: load.series.map((p: any) => p.atl) },
      ],
    };
  }, [load]);

  const strava = !!status?.connections.strava.connected;
  const komoot = !!status?.connections.komoot.connected;
  const cov = status?.coverage;
  const form = load?.status ? FORM_TEXT[load.status] : null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Home</h1>
          <div className="sub">
            {status?.last_run ? <>Synced {ago(status.last_run.started_at)} · {int(status.activities)} activities</> : "Not synced yet"}
          </div>
        </div>
      </div>

      <div className="stack gap16">
        {status && (!strava || !komoot || !status.last_run) && <SetupCard strava={strava} komoot={komoot} />}

        {cov && cov.activities > 0 && (
          <Card title="One history, both platforms" icon={IconSync}
            hint={`${int(cov.duplicates_hidden)} duplicates merged — every activity counts once`}
            actions={<Link to="/sync" className="small">Sync settings</Link>}>
            <div className="flow">
              <button className="ghost" style={{ flexDirection: "column", height: "auto", padding: 8 }} onClick={() => nav("/activities?presence=strava_only")}>
                <BrandIcon provider="strava" size={26} />
                <span className="big-num">{int(cov.strava_only)}</span>
                <span className="xs muted">only on Strava</span>
              </button>
              <button className="ghost" style={{ flexDirection: "column", height: "auto", padding: 8 }} onClick={() => nav("/activities?presence=both")}>
                <span className="row nowrap" style={{ gap: 4 }}><BrandIcon provider="strava" size={18} /><IconSync size={16} /><BrandIcon provider="komoot" size={18} /></span>
                <span className="big-num">{int(cov.both)}</span>
                <span className="xs muted">on both</span>
              </button>
              <button className="ghost" style={{ flexDirection: "column", height: "auto", padding: 8 }} onClick={() => nav("/activities?presence=komoot_only")}>
                <BrandIcon provider="komoot" size={26} />
                <span className="big-num">{int(cov.komoot_only)}</span>
                <span className="xs muted">only on Komoot</span>
              </button>
            </div>
          </Card>
        )}

        <FamilyChips value={families} onChange={setFamilies} />

        {isLoading || !data ? (
          <Skeleton h={200} />
        ) : (
          <>
            <div className="grid g2">
              <PeriodCard periods={data.periods} />
              <Card title="Form" icon={MetricIcon.load} hint="From the training load of every activity"
                actions={form && <span className={`badge ${form[0]}`} style={{ textTransform: "capitalize" }}>{load.status}</span>}>
                {load?.current ? (
                  <>
                    {form && <p className="secondary small" style={{ marginBottom: 12 }}>{form[1]}</p>}
                    <div className="stats" style={{ gridTemplateColumns: "repeat(3, minmax(0,1fr))", marginBottom: 8 }}>
                      <Stat label="Fitness" value={load.current.ctl.toFixed(0)} title="42-day average load (CTL)" />
                      <Stat label="Fatigue" value={load.current.atl.toFixed(0)} title="7-day average load (ATL)" />
                      <Stat label="Form" value={load.current.tsb.toFixed(0)} title="Fitness − fatigue (TSB)" />
                    </div>
                    {loadChart && <LineChart x={loadChart.x} series={loadChart.series} xTime height={150} yFormat={(v) => (Math.abs(v) < 10 ? v.toFixed(1) : v.toFixed(0))} />}
                    <div className="mt8 row between">
                      <Legend line items={loadChart ? loadChart.series.map((s) => ({ key: s.label, label: s.label, color: s.color })) : []} />
                      <Link to="/insights/fitness" className="small">Details</Link>
                    </div>
                  </>
                ) : <div className="empty">No training load yet</div>}
              </Card>
            </div>

            <Card title="Weekly volume" icon={MetricIcon.distance} hint="Last 6 months — tap a week to see its activities"
              actions={<select value={metric} onChange={(e) => setMetric(e.target.value as Metric)} style={{ width: "auto", minHeight: 36 }} aria-label="Metric">
                {METRICS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>}>
              {weekly && weekly.bars.some((b: any) => Object.values(b.values).some((v) => (v as number) > 0)) ? (
                <>
                  <StackedBars
                    data={weekly.bars}
                    series={weekly.series}
                    height={200}
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
              ) : <div className="empty">No activities in the last 6 months</div>}
            </Card>

            <div className="grid g2">
              <Card title="Recent activities" icon={IconList} flush actions={<Link to="/activities" className="small">All</Link>}>
                {data.recent.length ? <ActivityList items={data.recent.slice(0, 6)} /> : <div className="empty">No activities yet</div>}
              </Card>
              <Card title="Consistency" icon={IconTrophy}>
                <div className="stats">
                  <Stat icon="days" label="Day streak" value={data.streaks.current_days} unit="d" />
                  <Stat icon="days" label="Best day streak" value={data.streaks.longest_days} unit="d" />
                  <Stat icon="count" label="Week streak" value={data.streaks.current_weeks} unit="wk" />
                  <Stat icon="count" label="Best week streak" value={data.streaks.longest_weeks} unit="wk" />
                </div>
                <div className="mt16"><Link to="/insights/records" className="small">Records & best efforts →</Link></div>
              </Card>
            </div>
          </>
        )}
      </div>
    </>
  );
}
