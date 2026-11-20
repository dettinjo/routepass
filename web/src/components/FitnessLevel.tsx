import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { LineChart } from "./charts";
import {
  ICON, IconDone, IconFitness, IconInfo, IconRefresh, IconSparkles, IconTarget, IconTrendDown, IconTrendUp, IconWarn, MetricIcon, SportIcon,
} from "./icons";
import { Callout, Card, Empty, InfoTip, Seg, Skeleton, Stat, StatusBadge, useToast } from "./ui";
import { api } from "../lib/api";
import { familyColor } from "../lib/colors";
import { ago, duration, num } from "../lib/format";

const pace = (s?: number | null) => (s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}/km` : "–");
const CONF: Record<string, string> = { high: "Measured", medium: "Fair estimate", low: "Rough estimate" };

/** One sentence on where you stand; shown on Trends and on the fitness level tab. */
export function FitnessStateLine({ link = false }: { link?: boolean }) {
  const { data } = useQuery<any>({ queryKey: ["fitness"], queryFn: () => api("/insights/fitness", { params: { months: 24 } }), staleTime: 300_000 });
  if (!data?.state) return null;
  const ch = data.load?.change_6w_pct;
  const Icon = ch == null || Math.abs(ch) < 3 ? IconFitness : ch > 0 ? IconTrendUp : IconTrendDown;
  return (
    <div className="state-line">
      <Icon size={ICON.button} />
      <span>{data.state}</span>
      {link && <Link to="/insights/level" className="xs">Fitness level</Link>}
    </div>
  );
}

function CoachReport() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery<any>({
    queryKey: ["fitness-report"], queryFn: () => api("/insights/fitness-report"),
    refetchInterval: (q) => ((q.state.data as any)?.working ? 4000 : false),
  });
  const write = useMutation({
    mutationFn: () => api<any>("/insights/fitness-report", { method: "POST" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["fitness-report"] }); toast("The AI coach is writing your report — up to two minutes"); },
    onError: (e: Error) => toast(e.message, true),
  });
  if (!data) return <Skeleton h={160} />;
  const r = data.latest;
  const working = data.working || write.isPending;
  const button = (
    <button className="sm" disabled={working} onClick={() => write.mutate()}>
      <IconRefresh size={ICON.button} className={working ? "spin" : undefined} />{working ? "Writing…" : r ? "New report" : "Write report"}
    </button>
  );
  return (
    <Card title="Coach report" icon={IconSparkles} actions={button}
      hint={r ? `${r.model === "deterministic" ? "From your numbers" : "AI coach"} · ${ago(r.created_at)}` : "Written monthly, or when you ask"}>
      {working && <div className="coach-working" style={{ marginBottom: 10 }} role="status"><IconSparkles size={ICON.button} className="pulse" /><span>The AI coach is reading your numbers… Gemini can take a minute or two.</span></div>}
      {!r ? (
        <p className="small muted">No report yet. {data.ai?.configured ? "Ask for one, or wait for the monthly report." : <>Without a Gemini key the report is written from your numbers alone. <Link to="/settings/training">Add a key</Link></>}</p>
      ) : (
        <div className="stack" style={{ gap: 10 }}>
          <p className="review-headline">{r.headline}</p>
          {r.summary && r.summary !== r.headline && <p className="small secondary" style={{ margin: 0 }}>{r.summary}</p>}
          <div className="grid g2" style={{ gap: 12 }}>
            {r.strengths?.length > 0 && <div><div className="xs muted" style={{ marginBottom: 4 }}>Strengths</div><ul className="review-list good">{r.strengths.map((t: string, i: number) => <li key={i}><IconDone size={ICON.inline} />{t}</li>)}</ul></div>}
            {r.limiters?.length > 0 && <div><div className="xs muted" style={{ marginBottom: 4 }}>Holding you back</div><ul className="review-list warn">{r.limiters.map((t: string, i: number) => <li key={i}><IconWarn size={ICON.inline} />{t}</li>)}</ul></div>}
          </div>
          {r.changes && <p className="small secondary" style={{ margin: 0 }}><b>What changed:</b> {r.changes}</p>}
          {r.focus?.length > 0 && <div><div className="xs muted" style={{ marginBottom: 4 }}>Next 4 weeks</div><ul className="review-list">{r.focus.map((t: string, i: number) => <li key={i}><IconTarget size={ICON.inline} />{t}</li>)}</ul></div>}
          {r.ai_error && <span className="xs muted row nowrap" style={{ gap: 4 }}>The AI coach was unavailable<InfoTip label="Why">{r.ai_error}</InfoTip></span>}
          {data.history?.length > 0 && (
            <details className="more xs">
              <summary>Earlier reports</summary>
              <ul className="log-diff">{data.history.map((h: any) => <li key={h.created_at}><span className="muted">{new Date(h.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</span> — {h.headline}</li>)}</ul>
            </details>
          )}
        </div>
      )}
    </Card>
  );
}

function Basis({ x }: { x: any }) {
  if (!x?.confidence) return null;
  return <StatusBadge status={x.confidence === "high" ? "completed" : x.confidence === "medium" ? "planned" : "partial"} label={CONF[x.confidence]} />;
}

function CyclingCard({ c }: { c: any }) {
  return (
    <Card title="Cycling" icon={() => <SportIcon sport="Ride" size={ICON.header} />} actions={<Basis x={c} />}
      info="Threshold: power you could hold for about an hour. Without a power meter it is estimated from steady climbs: the watts needed to lift you and the bike at that rate, plus rolling and air resistance. VO2max from your best ~5-minute power.">
      {c.missing ? <p className="small muted">{c.missing}</p> : (
        <div className="stack" style={{ gap: 10 }}>
          <div className="stats">
            <Stat label="Threshold" value={num(c.threshold_wkg, 2)} unit=" W/kg" />
            <Stat label="Threshold power" value={Math.round(c.threshold_w)} unit=" W" />
            <Stat label="VO2max" value={num(c.vo2max, 0)} unit=" ml/kg/min" />
            {c.w_prime_kj != null && <Stat label="W′" value={num(c.w_prime_kj, 1)} unit=" kJ" info="Anaerobic work capacity above critical power." />}
          </div>
          {c.best_climbs?.length > 0 && (
            <div>
              <div className="xs muted" style={{ marginBottom: 4 }}>Climbs behind the estimate{c.older ? " (older than 4 months)" : ""}</div>
              <ul className="log-diff small">
                {c.best_climbs.map((b: any, i: number) => (
                  <li key={i}>
                    <Link to={`/activities/${b.activity.id}`}>{b.activity.name}</Link> <span className="muted">{new Date(b.activity.date).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</span>
                    {" · "}{num(b.length_m / 1000, 1)} km at {num(b.grade_pct, 1)} % in {duration(b.duration_s)} · ≈ {b.power_w} W
                  </li>
                ))}
              </ul>
            </div>
          )}
          {c.note && <p className="xs muted" style={{ margin: 0 }}>{c.note}{c.profile_ftp ? ` Your profile FTP: ${c.profile_ftp} W.` : ""}</p>}
        </div>
      )}
    </Card>
  );
}

function RunningCard({ r }: { r: any }) {
  return (
    <Card title="Running" icon={() => <SportIcon sport="Run" size={ICON.header} />} actions={<Basis x={r} />}
      info="VO2max (Daniels' VDOT) from your best run of 5 km or more in the last year; predictions assume the same fitness and a flat course.">
      {r.missing ? <p className="small muted">{r.missing}</p> : (
        <div className="stack" style={{ gap: 10 }}>
          <div className="stats">
            <Stat label="VO2max" value={num(r.vo2max, 1)} />
            <Stat label="Threshold pace" value={pace(r.threshold_pace_s_per_km)} />
          </div>
          <div className="table-wrap"><table className="small">
            <tbody>
              {r.predictions.map((p: any) => <tr key={p.label}><td>{p.label}</td><td className="num">{duration(p.time_s, true)}</td><td className="num muted">{pace(p.time_s / (p.distance_m / 1000))}</td></tr>)}
              {r.trail_prediction && (
                <tr><td>{r.trail_prediction.label} <span className="xs muted">({r.trail_prediction.distance_km} km, {r.trail_prediction.elevation_gain_m} m)</span></td><td className="num">{duration(r.trail_prediction.time_s)}</td><td className="num muted">rough</td></tr>
              )}
            </tbody>
          </table></div>
          <p className="xs muted" style={{ margin: 0 }}>
            From <Link to={`/activities/${r.from_effort.activity.id}`}>{r.from_effort.activity.name}</Link>: {num(r.from_effort.distance_m / 1000, r.from_effort.distance_m < 5000 ? 2 : 0)} km in {duration(r.from_effort.time_s, true)}.
            {r.from_effort.trail ? " A trail run understates road speed." : ""}
          </p>
        </div>
      )}
    </Card>
  );
}

function OutlookCard({ l, d, hr }: { l: any; d: any; hr: any }) {
  if (!l?.ctl && l?.ctl !== 0) return null;
  return (
    <Card title="Fitness outlook" icon={IconFitness} info="Fitness is your training load over about six weeks. “In 6 weeks” assumes you keep your average daily load of the last four weeks.">
      <div className="stats">
        <Stat label="Fitness now" value={num(l.ctl, 0)} delta={l.change_6w_pct} title="Change over six weeks" />
        <Stat label="6 weeks ago" value={l.ctl_6w_ago != null ? num(l.ctl_6w_ago, 0) : "–"} />
        <Stat label="A year ago" value={l.ctl_1y_ago != null ? num(l.ctl_1y_ago, 0) : "–"} />
        <Stat label="In 6 weeks at this load" value={num(l.ctl_in_6w_at_this_load, 0)} />
        {hr?.vo2max && <Stat label="VO2max (heart rate)" value={num(hr.vo2max, 0)} info={hr.note} />}
        {d?.decoupling_pct != null && <Stat label="Heart-rate drift" value={num(d.decoupling_pct, 1)} unit=" %" info={d.note} />}
      </div>
    </Card>
  );
}

function TrendCard({ trend }: { trend: any[] }) {
  const hasC = trend.some((t) => t.cycling_wkg != null);
  const hasR = trend.some((t) => t.running_vo2max != null);
  const [which, setWhich] = useState<"cycling" | "running">(hasC ? "cycling" : "running");
  const chart = useMemo(() => {
    const x = trend.map((t) => new Date(`${t.month}-15T12:00:00`).getTime() / 1000);
    return which === "cycling"
      ? { x, series: [{ label: "Threshold W/kg", color: familyColor("ride"), values: trend.map((t) => t.cycling_wkg), width: 2 }], fmt: (v: number) => v.toFixed(2) }
      : { x, series: [{ label: "Running VO2max", color: familyColor("run"), values: trend.map((t) => t.running_vo2max), width: 2 }], fmt: (v: number) => v.toFixed(1) };
  }, [trend, which]);
  if (!hasC && !hasR) return null;
  return (
    <Card title="Over time" icon={MetricIcon.load} hint="Each month: best of the previous 4 months (cycling) or 12 months (running)"
      actions={hasC && hasR ? <Seg value={which} onChange={setWhich} options={[{ value: "cycling", label: "Cycling" }, { value: "running", label: "Running" }]} /> : undefined}>
      <LineChart x={chart.x} series={chart.series} xTime height={200} yFormat={chart.fmt} />
    </Card>
  );
}

export function FitnessLevel() {
  const { data, isLoading } = useQuery<any>({ queryKey: ["fitness"], queryFn: () => api("/insights/fitness", { params: { months: 24 } }), staleTime: 300_000 });
  if (isLoading) return <Skeleton h={400} />;
  if (!data) return <Empty title="No data yet" icon={IconFitness}>Record a few activities to see your fitness level.</Empty>;
  return (
    <div className="stack gap16">
      <FitnessStateLine />
      <CoachReport />
      <div className="grid g2">
        <CyclingCard c={data.cycling} />
        <RunningCard r={data.running} />
      </div>
      <OutlookCard l={data.load} d={data.durability} hr={data.heart_rate} />
      <TrendCard trend={data.trend || []} />
      {data.needs?.length > 0 && (
        <Callout kind="info">
          <b>Make these estimates better</b>
          <ul className="plain-list small" style={{ margin: "4px 0" }}>{data.needs.map((n: string) => <li key={n}>{n}</li>)}</ul>
          <Link to="/settings/profile" className="small">Open your profile</Link>
        </Callout>
      )}
      <p className="xs muted row nowrap" style={{ gap: 4 }}><IconInfo size={ICON.inline} />RoutePass computes these numbers from your recordings; the AI coach only explains them.</p>
    </div>
  );
}
