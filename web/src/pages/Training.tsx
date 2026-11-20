import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { TrailTab } from "../components/TrailTab";
import {
  ICON, IconAdapt, IconAdapted, IconAttention, IconCalendarAdd, IconCalendarSynced, IconChevronDownSm, IconInjury, IconKeySession, IconLeft,
  IconPlus, IconRace, IconRight, IconSick, IconSore, IconStatusDone, IconStatusSkipped, IconStreak, IconSync, IconTime,
  IconTired, IconTraining, IconTrash, KEYED_ICON, MetricIcon, PlanSportIcon, SportIcon,
  IconInfo, IconStatusFailed, IconStatusPlanned, IconUndo, IconCalendarStat, IconSparkles, IconWarn, IconDone,
} from "../components/icons";
import { Attention, Callout, Card, Empty, InfoTip, Menu, ProgressBar, Seg, Skeleton, Stat, StatusBadge, Tabs, useToast, type Severity } from "../components/ui";
import { api } from "../lib/api";
import { planSportColor } from "../lib/colors";
import { ago, duration, int, num } from "../lib/format";
import { useSavePrefs } from "../lib/hooks";

type PlanType = "trail_run" | "road_run" | "cycling" | "triathlon" | "duathlon" | "base_build";

const PLAN_TYPE_LABELS: Record<PlanType, string> = {
  trail_run: "Trail run", road_run: "Road run", cycling: "Cycling", triathlon: "Triathlon", duathlon: "Duathlon", base_build: "Base build",
};
const SPORT_LABEL: Record<string, string> = {
  trail_run: "Trail run", run: "Run", bike: "Ride", ride: "Ride", cycling: "Ride", swim: "Swim", strength: "Strength",
  brick: "Brick", recovery: "Recovery", rest: "Rest",
};
const PHASE_LABEL: Record<string, string> = { base: "Base", build: "Build", peak: "Peak", recovery: "Recovery week", taper: "Taper", race_week: "Race week" };

/** Plan verdicts. Behind plan is attention (amber), never an error; too little data is neutral. */
const VERDICT: Record<string, { label: string; status: string }> = {
  on_track: { label: "On track", status: "completed" },
  catchable: { label: "Slightly behind", status: "partial" },
  at_risk: { label: "Behind plan", status: "missed" },
  early: { label: "Too early to judge", status: "planned" },
};
const SESSION_STATUS: Record<string, { label: string; status: string }> = {
  completed: { label: "Done", status: "completed" },
  partial: { label: "Partly done", status: "partial" },
  missed: { label: "Missed", status: "missed" },
  moved: { label: "Adapted", status: "running" },
  skipped: { label: "Skipped", status: "skipped" },
  planned: { label: "Planned", status: "planned" },
};
const SKIP_REASONS = [
  { id: "time", icon: IconTime, label: "No time" },
  { id: "sickness", icon: IconSick, label: "Sick" },
  { id: "muscle_pain", icon: IconSore, label: "Sore muscles" },
  { id: "fatigue", icon: IconTired, label: "Not recovered" },
  { id: "injury", icon: IconInjury, label: "Injury" },
] as const;
type SkipReason = (typeof SKIP_REASONS)[number]["id"];
type SkipSeverity = "mild" | "moderate" | "severe";

// ── formatting ────────────────────────────────────────────────────────────────
function hm(sec: number | null | undefined): string {
  if (sec == null || sec <= 0) return "–";
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}
function pace(secPerKm: number | null | undefined): string {
  if (secPerKm == null || secPerKm <= 0) return "–";
  const m = Math.floor(secPerKm / 60);
  return `${m}:${String(Math.round(secPerKm % 60)).padStart(2, "0")} /km`;
}
function parseHm(hmStr: string): number | null {
  const parts = hmStr.trim().split(":").map(Number);
  if (!hmStr.trim() || parts.some(Number.isNaN)) return null;
  if (parts.length === 2) return parts[0] * 3600 + parts[1] * 60;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return null;
}
const localIso = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const asDate = (iso: string) => new Date(`${iso}T12:00:00`);
function addDays(iso: string, days: number): string {
  const d = asDate(iso);
  d.setDate(d.getDate() + days);
  return localIso(d);
}
function dayLabel(iso: string, today: string): string {
  if (iso === today) return "Today";
  if (iso === addDays(today, 1)) return "Tomorrow";
  if (iso === addDays(today, -1)) return "Yesterday";
  return asDate(iso).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}
const timeSlot = (s: any) =>
  s.scheduled_start && s.scheduled_end ? `${s.scheduled_start.slice(11, 16)}–${s.scheduled_end.slice(11, 16)}` : s.scheduled_slot && s.scheduled_slot !== "flexible" ? s.scheduled_slot : null;

// ── small pieces ──────────────────────────────────────────────────────────────
function PlanSportBadge({ sport, size = 40 }: { sport: string; size?: number }) {
  const color = planSportColor(sport);
  return (
    <span className="sport-badge" style={{ width: size, height: size, background: `color-mix(in srgb, ${color} 16%, transparent)`, color }}>
      <PlanSportIcon sport={sport} size={Math.round(size * 0.5)} />
    </span>
  );
}

function SessionMetrics({ s }: { s: any }) {
  return (
    <div className="metrics">
      <span><MetricIcon.time size={ICON.inline} />{duration(s.target_duration_s)}</span>
      {s.target_distance_km > 0 && <span><MetricIcon.distance size={ICON.inline} />{num(s.target_distance_km, 1)} km</span>}
      {s.target_elev_m > 0 && <span><MetricIcon.elevation size={ICON.inline} />{int(s.target_elev_m)} m</span>}
      {s.target_tss > 0 && <span><MetricIcon.load size={ICON.inline} />{int(s.target_tss)} load</span>}
    </div>
  );
}

function LinkedActivity({ a, compliance }: { a: any; compliance: number | null }) {
  return (
    <Link to={`/activities/${a.id}`} className="linked">
      <SportIcon sport={a.sport} family={a.family} size={ICON.button} />
      <span className="grow ellipsis"><b>{a.name}</b> · {a.distance_m ? `${num(a.distance_m / 1000, 1)} km · ` : ""}{duration(a.moving_time_s)}</span>
      {compliance != null && <span className="muted small">{Math.round(compliance)}% of target</span>}
      <IconRight size={ICON.button} className="muted" />
    </Link>
  );
}

// ── compliance, targets, feedback ────────────────────────────────────────────
/** TrainingPeaks-style session colours; always shown with an icon and a word. */
const COMPLIANCE: Record<string, { label: string; color: string; icon: React.ComponentType<{ size?: number; style?: React.CSSProperties }> }> = {
  on: { label: "On target", color: "var(--good)", icon: IconStatusDone },
  partial: { label: "Partly done", color: "var(--warn)", icon: IconAttention },
  off: { label: "Far off target", color: "var(--serious)", icon: IconAttention },
  missed: { label: "Missed", color: "var(--bad)", icon: IconStatusFailed },
  skipped: { label: "Skipped", color: "var(--neutral)", icon: IconStatusSkipped },
  planned: { label: "Planned", color: "var(--border-strong)", icon: IconStatusPlanned },
};

function ComplianceMark({ level, sport }: { level: string; sport: string }) {
  const c = COMPLIANCE[level] ?? COMPLIANCE.planned;
  if (level === "planned") return <span className="status-dot" style={{ background: planSportColor(sport) }} title={`Planned · ${SPORT_LABEL[sport] ?? sport}`} />;
  return <span title={c.label} style={{ display: "inline-flex" }}><c.icon size={13} style={{ color: c.color }} /></span>;
}

const RUN_SPORTS = new Set(["run", "trail_run", "brick"]);
const BIKE_SPORTS = new Set(["bike", "ride", "cycling"]);

/** "6:10–6:40 /km · 128–142 bpm" for a zone, in the units that fit the sport. */
function zoneRange(zones: any, zone: string | null | undefined, sport: string): string | null {
  if (!zones || !zone) return null;
  const parts: string[] = [];
  if (RUN_SPORTS.has(sport) && zones.pace?.[zone]) {
    const [fast, slow] = zones.pace[zone];
    parts.push(`${pace(fast).replace(" /km", "")}–${pace(slow)}`);
  }
  if (BIKE_SPORTS.has(sport) && zones.power?.[zone]) parts.push(`${zones.power[zone][0]}–${zones.power[zone][1]} W`);
  if (zones.hr?.[zone]) parts.push(`${zones.hr[zone][0]}–${zones.hr[zone][1]} bpm`);
  return parts.length ? parts.join(" · ") : null;
}

/** Puts your numbers next to zone mentions in workout steps: "Z2" → "Z2 (6:10–6:40 /km · 128–142 bpm)". */
function annotate(step: string, zones: any, sport: string): string {
  return step.replace(/\bZ(\d)(?:\s*[–-]\s*Z?(\d))?\b/g, (m, a, b) => {
    const lo = zoneRange(zones, a, sport);
    const hi = b ? zoneRange(zones, b, sport) : null;
    if (!lo) return m;
    return hi && b !== a ? `${m} (${lo.split(" · ")[0]} → ${hi.split(" · ")[0]})` : `${m} (${lo})`;
  });
}

function Targets({ s, zones }: { s: any; zones: any }) {
  const range = zoneRange(zones, s.zone, s.sport);
  if (!s.zone) return null;
  return (
    <div className="targets">
      <span className="row nowrap" style={{ gap: 4 }}><MetricIcon.hr size={ICON.inline} />Mostly zone {s.zone}</span>
      {range ? <b>{range}</b> : <Link to="/settings/profile" className="small">Add max heart rate for your numbers</Link>}
    </div>
  );
}

function WhyLine({ text }: { text?: string }) {
  return text ? <p className="why"><IconInfo size={ICON.inline} />{text}</p> : null;
}

const FEEL_LABEL: Record<string, string> = { easy: "Too easy", right: "About right", hard: "Too hard" };

/** "How did it feel?" — effort 1–10 plus too easy / right / too hard. */
function Feedback({ s, busy, onSave }: { s: any; busy: boolean; onSave: (rpe: number | null, feel: string | null) => void }) {
  const [editing, setEditing] = useState(false);
  const [feel, setFeel] = useState<string | null>(s.feel ?? null);
  const [rpe, setRpe] = useState<number | null>(s.rpe ?? null);
  if ((s.feel || s.rpe) && !editing) {
    return (
      <div className="feedback">
        <span className="row between nowrap">
          <span>Felt <b>{s.feel ? FEEL_LABEL[s.feel].toLowerCase() : "rated"}</b>{s.rpe ? ` · effort ${s.rpe}/10` : ""}</span>
          <button className="sm ghost" onClick={() => setEditing(true)}>Change</button>
        </span>
      </div>
    );
  }
  return (
    <div className="feedback">
      <b>How did it feel?</b>
      <Seg block value={(feel ?? "") as string} onChange={(v) => setFeel(v)} options={[{ value: "easy", label: "Too easy" }, { value: "right", label: "About right" }, { value: "hard", label: "Too hard" }]} />
      <div>
        <div className="rpe-scale" role="group" aria-label="Effort from 1 to 10">
          {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
            <button key={n} type="button" className={rpe === n ? "on" : ""} onClick={() => setRpe(rpe === n ? null : n)} aria-label={`Effort ${n} of 10`}>{n}</button>
          ))}
        </div>
        <div className="rpe-ends"><span>very easy</span><span>all out</span></div>
      </div>
      <span className="xs muted">Your effort counts as training load when no heart rate was recorded.</span>
      <div className="row">
        <button className="sm primary" disabled={busy || (!feel && !rpe)} onClick={() => { onSave(rpe, feel); setEditing(false); }}><IconStatusDone size={ICON.button} />Save</button>
        {editing && <button className="sm ghost" onClick={() => setEditing(false)}>Cancel</button>}
      </div>
    </div>
  );
}

/** Today's options: the plan as is, shorter, easier, swap, skip — or undo a change. */
function SessionOptions({ s, busy, onVariant, onSkip, compact = false }: {
  s: any; busy: boolean; onVariant: (kind: string, minutes?: number) => void; onSkip: () => void; compact?: boolean;
}) {
  const [short, setShort] = useState(false);
  const full = Math.round((s.target_duration_s || 3600) / 60);
  const choices = [20, 30, 45, 60, 75, 90].filter((m) => m < full);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="option-row">
        {s.changed && <button className="sm" disabled={busy} onClick={() => onVariant("original")}><IconUndo size={ICON.button} />Back to the plan</button>}
        {choices.length > 0 && <button className={`sm ${short ? "primary" : ""}`} disabled={busy} onClick={() => setShort(!short)}><IconTime size={ICON.button} />Shorter</button>}
        {s.session_type !== "easy" && s.session_type !== "recovery" && <button className="sm" disabled={busy} onClick={() => onVariant("easier")}><IconTired size={ICON.button} />Easier</button>}
        <button className="sm" disabled={busy} onClick={() => onVariant("swap")}><IconSync size={ICON.button} />Swap with next</button>
        {!compact && <button className="sm ghost" disabled={busy} onClick={onSkip}><IconStatusSkipped size={ICON.button} />Skip…</button>}
      </div>
      {short && (
        <div className="row">
          <span className="small secondary">I have</span>
          {choices.map((m) => <button key={m} className="chip" disabled={busy} onClick={() => { setShort(false); onVariant("shorter", m); }}>{m} min</button>)}
        </div>
      )}
    </div>
  );
}

/** Month overview: compliance per day and planned vs done hours per week. */
function MonthView({ sessions, today, onPick }: { sessions: any[]; today: string; onPick: (date: string) => void }) {
  const [anchor, setAnchor] = useState(today.slice(0, 7));
  const first = asDate(`${anchor}-01`);
  const start = addDays(`${anchor}-01`, -((first.getDay() + 6) % 7));
  const byDate = useMemo(() => {
    const m: Record<string, any[]> = {};
    for (const s of sessions) if (s.sport !== "rest") (m[s.scheduled_date] ||= []).push(s);
    return m;
  }, [sessions]);
  const weeks = Array.from({ length: 6 }, (_, w) => Array.from({ length: 7 }, (_, d) => addDays(start, w * 7 + d)))
    .filter((wk) => wk.some((d) => d.startsWith(anchor)));
  const shift = (n: number) => { const d = asDate(`${anchor}-01`); d.setMonth(d.getMonth() + n); setAnchor(localIso(d).slice(0, 7)); };
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row between nowrap">
        <button className="ghost icon sm" aria-label="Previous month" onClick={() => shift(-1)}><IconLeft size={ICON.button} /></button>
        <b>{first.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</b>
        <button className="ghost icon sm" aria-label="Next month" onClick={() => shift(1)}><IconRight size={ICON.button} /></button>
      </div>
      <div className="month-grid">
        {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => <span key={i} className="hd">{d}</span>)}
        <span className="hd">Week</span>
        {weeks.map((wk) => {
          const ss = wk.flatMap((d) => byDate[d] || []);
          const planned = ss.reduce((t, s) => t + (s.target_duration_s || 0), 0);
          const done = ss.reduce((t, s) => t + (s.matched_activity?.moving_time_s || 0), 0);
          return [
            ...wk.map((d) => (
              <button key={d} className={`day ${d.startsWith(anchor) ? "" : "out"} ${d === today ? "today" : ""}`} onClick={() => onPick(d)}
                aria-label={`${asDate(d).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}: ${(byDate[d] || []).map((s) => `${s.title}, ${(COMPLIANCE[s.compliance_level] ?? COMPLIANCE.planned).label}`).join("; ") || "rest"}`}>
                {asDate(d).getDate()}
                <span className="dots">{(byDate[d] || []).map((s) => <ComplianceMark key={s.id} level={s.compliance_level} sport={s.sport} />)}</span>
              </button>
            )),
            <span key={`${wk[0]}-t`} className="wk" title={planned ? `${hm(done) === "–" ? "0m" : hm(done)} done of ${hm(planned)} planned` : undefined}>
              {planned ? <><b>{(done / 3600).toFixed(1)}</b><span className="muted">/{(planned / 3600).toFixed(1)} h</span></> : null}
            </span>,
          ];
        })}
      </div>
      <div className="compliance-legend">
        {["on", "partial", "off", "missed", "skipped"].map((k) => { const c = COMPLIANCE[k]; return <span key={k}><c.icon size={13} style={{ color: c.color }} />{c.label}</span>; })}
        <span><span className="status-dot" style={{ background: "var(--text-muted)" }} />Planned</span>
      </div>
    </div>
  );
}

function SkipDrawer({ busy, onApply, onCancel }: { busy: boolean; onApply: (r: SkipReason, sev: SkipSeverity, note: string) => void; onCancel: () => void }) {
  const [reason, setReason] = useState<SkipReason>("time");
  const [sev, setSev] = useState<SkipSeverity>("moderate");
  const [note, setNote] = useState("");
  return (
    <div className="skip-drawer">
      <b className="small">Why are you skipping it? The next days are adapted (and your calendar moved) to match.</b>
      <div className="chips" style={{ flexWrap: "wrap" }}>
        {SKIP_REASONS.map((r) => (
          <button key={r.id} type="button" className={`chip ${reason === r.id ? "on" : ""}`} onClick={() => setReason(r.id)}>
            <r.icon size={ICON.button} />{r.label}
          </button>
        ))}
      </div>
      {reason !== "time" && (
        <Seg value={sev} onChange={setSev} options={[{ value: "mild", label: "Mild" }, { value: "moderate", label: "Moderate" }, { value: "severe", label: "Severe" }]} />
      )}
      <input placeholder="Optional note, e.g. “tight left calf”" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="row">
        <button className="primary sm" disabled={busy} onClick={() => onApply(reason, sev, note)}><IconAdapt size={ICON.button} />{busy ? "Adapting…" : "Skip and adapt plan"}</button>
        <button className="ghost sm" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

// ── trajectory chart ──────────────────────────────────────────────────────────
/** Fitness (CTL) or predicted finish by plan week. Lines are ink, never sport or status colours:
 *  solid = what happened / where you are heading, dashed = the plan. */
function TrajectoryChart({ trajectory, targetTimeS, rangePct, mode }: { trajectory: any[]; targetTimeS: number | null; rangePct: number; mode: "ctl" | "time" }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<number | null>(null);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(ref.current);
    setWidth(Math.floor(ref.current.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, []);
  if (!trajectory.length) return <Empty title="No trajectory yet" />;

  const height = 230, padL = 52, padR = 12, padT = 18, padB = 26;
  const innerW = Math.max(width - padL - padR, 40), innerH = height - padT - padB;
  const n = trajectory.length;
  const xOf = (i: number) => padL + (n === 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const todayIdx = trajectory.reduce((acc, p, i) => (!p.is_future ? i : acc), 0);
  const band = rangePct / 100;

  let minV: number, maxV: number;
  if (mode === "ctl") {
    const vals = trajectory.flatMap((p) => [p.actual_ctl, p.planned_ctl, p.projected_ctl_optimal, p.projected_ctl_trend].filter((v) => v != null));
    minV = Math.max(0, Math.floor((Math.min(...vals, 0) - 5) / 5) * 5);
    maxV = Math.ceil((Math.max(...vals, 20) + 8) / 5) * 5;
  } else {
    const vals = trajectory.map((p) => p.predicted_time_s).filter((v) => v > 0);
    if (targetTimeS) vals.push(targetTimeS);
    minV = Math.max(600, Math.min(...vals) * (1 - band - 0.03));
    maxV = Math.max(...vals) * (1 + band + 0.03);
  }
  const span = Math.max(1, maxV - minV);
  const yOf = (v: number) => padT + innerH - ((v - minV) / span) * innerH;
  const path = (pts: [number, number][]) => pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => minV + f * span);

  const planned: [number, number][] = trajectory.map((p, i) => [xOf(i), yOf(p.planned_ctl)]);
  const actual = trajectory.flatMap((p, i) => (p.actual_ctl != null ? [[xOf(i), yOf(p.actual_ctl)] as [number, number]] : []));
  const optimal: [number, number][] = trajectory.slice(todayIdx).map((p, k) => [xOf(todayIdx + k), yOf(p.projected_ctl_optimal)]);
  const trend: [number, number][] = trajectory.slice(todayIdx).map((p, k) => [xOf(todayIdx + k), yOf(p.projected_ctl_trend)]);
  const time: [number, number][] = trajectory.map((p, i) => [xOf(i), yOf(p.predicted_time_s)]);
  const timeBand = `${path(trajectory.map((p, i) => [xOf(i), yOf(p.predicted_time_s * (1 + band))]))} L${[...trajectory].reverse().map((p, k) => `${xOf(n - 1 - k).toFixed(1)},${yOf(p.predicted_time_s * (1 - band)).toFixed(1)}`).join(" L")} Z`;
  const hp = hover != null ? trajectory[hover] : null;

  const legend: { label: string; dash?: boolean; color: string }[] = mode === "ctl"
    ? [
      ...(actual.length ? [{ label: "Your fitness", color: "var(--line-1)" }] : []),
      { label: "Heading (current trend)", color: "var(--line-1)", dash: true },
      { label: "If you follow the plan", color: "var(--line-2)", dash: true },
    ]
    : [{ label: `Predicted finish (±${rangePct}%)`, color: "var(--line-1)" }, ...(targetTimeS ? [{ label: "Your goal", color: "var(--line-2)", dash: true }] : [])];

  return (
    <div className="chart" ref={ref} onMouseLeave={() => setHover(null)}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={mode === "ctl" ? "Fitness by plan week" : "Predicted finish time by plan week"}>
          {ticks.map((t, i) => (
            <g key={i}>
              <line className="gridline" x1={padL} x2={width - padR} y1={yOf(t)} y2={yOf(t)} />
              <text x={padL - 6} y={yOf(t) + 4} textAnchor="end">{mode === "ctl" ? Math.round(t) : hm(t)}</text>
            </g>
          ))}
          <line x1={xOf(todayIdx)} x2={xOf(todayIdx)} y1={padT} y2={padT + innerH} stroke="var(--text-muted)" strokeDasharray="2 3" />
          <text x={xOf(todayIdx)} y={padT - 6} textAnchor="middle">Today</text>
          {mode === "ctl" ? (
            <>
              {optimal.length > 1 && <path d={`${path(optimal)} L${[...trend].reverse().map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" L")} Z`} style={{ fill: "var(--surface-3)" }} />}
              <path d={path(planned)} fill="none" stroke="var(--line-2)" strokeWidth={1.5} strokeDasharray="5 4" />
              {optimal.length > 1 && <path d={path(optimal)} fill="none" stroke="var(--line-2)" strokeWidth={1.5} strokeDasharray="5 4" />}
              {trend.length > 1 && <path d={path(trend)} fill="none" stroke="var(--line-1)" strokeWidth={2} strokeDasharray="6 4" />}
              {actual.length > 1 && <path d={path(actual)} fill="none" stroke="var(--line-1)" strokeWidth={2.5} />}
              {actual.length === 1 && <circle cx={actual[0][0]} cy={actual[0][1]} r={4} style={{ fill: "var(--line-1)" }} />}
            </>
          ) : (
            <>
              <path d={timeBand} style={{ fill: "var(--surface-3)" }} />
              {targetTimeS && (
                <>
                  <line x1={padL} x2={width - padR} y1={yOf(targetTimeS)} y2={yOf(targetTimeS)} stroke="var(--line-2)" strokeWidth={1.5} strokeDasharray="6 4" />
                  <text x={width - padR} y={yOf(targetTimeS) - 5} textAnchor="end">Goal {hm(targetTimeS)}</text>
                </>
              )}
              <path d={path(time)} fill="none" stroke="var(--line-1)" strokeWidth={2.2} />
            </>
          )}
          {trajectory.map((p, i) => {
            const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(innerW / 56))));
            return i % every === 0 || i === n - 1 ? <text key={p.week_index} x={xOf(i)} y={height - 6} textAnchor="middle">W{p.week_index}</text> : null;
          })}
          {trajectory.map((p, i) => {
            const colW = innerW / Math.max(1, n);
            return <rect key={`h${p.week_index}`} x={xOf(i) - colW / 2} y={padT} width={colW} height={innerH} fill="transparent" onMouseEnter={() => setHover(i)} onClick={() => setHover(i)} />;
          })}
          {hover != null && <line x1={xOf(hover)} x2={xOf(hover)} y1={padT} y2={padT + innerH} stroke="var(--text-muted)" />}
        </svg>
      )}
      {hp && width > 0 && (
        <div className="tooltip" style={{ left: Math.min(Math.max(xOf(hover!) + 10, 8), Math.max(width - 210, 8)), top: 12 }}>
          <div className="tt-title">Week {hp.week_index} · {PHASE_LABEL[hp.phase] ?? hp.phase}</div>
          {mode === "ctl" ? (
            <>
              {hp.actual_ctl != null && <div className="tt-row"><span>Your fitness</span><span>{hp.actual_ctl}</span></div>}
              <div className="tt-row"><span>Plan</span><span>{hp.planned_ctl}</span></div>
              {hp.is_future && <div className="tt-row"><span>Current trend</span><span>{hp.projected_ctl_trend}</span></div>}
            </>
          ) : (
            <>
              <div className="tt-row"><span>Predicted</span><span>{hm(hp.predicted_time_s * (1 - band))}–{hm(hp.predicted_time_s * (1 + band))}</span></div>
              {targetTimeS && <div className="tt-row"><span>Goal</span><span>{hm(targetTimeS)}</span></div>}
            </>
          )}
        </div>
      )}
      <div className="legend mt8">
        {legend.map((l) => (
          <span className="item-l" key={l.label} style={{ color: l.color }}>
            <i className={l.dash ? "dash" : "ln"} style={l.dash ? undefined : { background: l.color }} />
            <span className="secondary">{l.label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ── plan creation ─────────────────────────────────────────────────────────────
function CreatePlanWizard({ onCreated, onCancel, aiConfigured }: { onCreated: (id: number) => void; onCancel?: () => void; aiConfigured: boolean }) {
  const toast = useToast();
  const qc = useQueryClient();
  const defaultDate = useMemo(() => addDays(localIso(), 84), []);
  const [planType, setPlanType] = useState<PlanType>("trail_run");
  const [name, setName] = useState("50k Trail Race");
  const [eventDate, setEventDate] = useState(defaultDate);
  const [runKm, setRunKm] = useState("50");
  const [runElev, setRunElev] = useState("2200");
  const [bikeKm, setBikeKm] = useState("90");
  const [bikeElev, setBikeElev] = useState("1000");
  const [swimKm, setSwimKm] = useState("1.9");
  const [goalTime, setGoalTime] = useState("");
  const [maxHours, setMaxHours] = useState("8");
  const [slot, setSlot] = useState("evening");
  const [useAi, setUseAi] = useState(aiConfigured);

  const presets: Record<PlanType, () => void> = {
    trail_run: () => { setName("50k Trail Race"); setRunKm("50"); setRunElev("2200"); },
    road_run: () => { setName("Half Marathon"); setRunKm("21.1"); setRunElev("100"); },
    cycling: () => { setName("Gran Fondo 140k"); setBikeKm("140"); setBikeElev("2200"); },
    triathlon: () => { setName("70.3 Triathlon"); setSwimKm("1.9"); setBikeKm("90"); setBikeElev("900"); setRunKm("21.1"); setRunElev("150"); },
    duathlon: () => { setName("Long Duathlon"); setBikeKm("60"); setBikeElev("600"); setRunKm("15"); setRunElev("100"); },
    base_build: () => setName("Multi-sport base"),
  };
  const showRun = ["trail_run", "road_run", "triathlon", "duathlon"].includes(planType);
  const showBike = ["cycling", "triathlon", "duathlon"].includes(planType);
  const showSwim = planType === "triathlon";

  const create = useMutation({
    mutationFn: () => {
      const targets: Record<string, number> = {};
      if (showRun) { targets.run_km = Number(runKm) || 21.1; targets.run_elev_m = Number(runElev) || 0; }
      if (showBike) { targets.bike_km = Number(bikeKm) || 90; targets.bike_elev_m = Number(bikeElev) || 0; }
      if (showSwim) targets.swim_km = Number(swimKm) || 1.9;
      const target = parseHm(goalTime);
      return api<any>("/training/plans", {
        method: "POST",
        body: {
          name: name.trim() || PLAN_TYPE_LABELS[planType], plan_type: planType, event_date: eventDate, start_date: localIso(),
          goal_spec: { targets, ...(target ? { target_time_s: target } : {}) },
          schedule_prefs: { max_weekly_hours: Number(maxHours) || 8, preferred_slot: slot, rest_days: [0] },
          use_ai: useAi, set_active: true,
        },
      });
    },
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["training-plans"] });
      toast(p.ai?.coach?.busy ? `Created ${p.name} — the AI coach is writing the first sessions` : `Created ${p.name}`);
      onCreated(p.id);
    },
    onError: (e: Error) => toast(e.message, true),
  });

  return (
    <Card title="New training plan" icon={IconTraining} hint="Built around your recent training; sessions start today"
      actions={onCancel ? <button className="sm ghost" onClick={onCancel}>Cancel</button> : undefined}>
      <div className="stack gap16">
        <div className="chips" style={{ flexWrap: "wrap" }} role="group" aria-label="Goal type">
          {(Object.keys(PLAN_TYPE_LABELS) as PlanType[]).map((t) => (
            <button key={t} type="button" className={`chip ${planType === t ? "on" : ""}`} onClick={() => { setPlanType(t); presets[t](); }}>
              <PlanSportIcon sport={t} size={ICON.button} />{PLAN_TYPE_LABELS[t]}
            </button>
          ))}
        </div>
        <div className="fields">
          <label className="field">Goal or race<input value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="field">Race date<input type="date" value={eventDate} min={addDays(localIso(), 14)} onChange={(e) => setEventDate(e.target.value)} /></label>
          <label className="field">Goal time (optional)<input placeholder="h:mm, e.g. 6:30" inputMode="numeric" value={goalTime} onChange={(e) => setGoalTime(e.target.value)} /></label>
        </div>
        <div className="fields">
          {showSwim && <label className="field">Swim (km)<input type="number" step="0.1" value={swimKm} onChange={(e) => setSwimKm(e.target.value)} /></label>}
          {showBike && <>
            <label className="field">Bike (km)<input type="number" step="1" value={bikeKm} onChange={(e) => setBikeKm(e.target.value)} /></label>
            <label className="field">Bike climbing (m)<input type="number" step="50" value={bikeElev} onChange={(e) => setBikeElev(e.target.value)} /></label>
          </>}
          {showRun && <>
            <label className="field">Run (km)<input type="number" step="0.5" value={runKm} onChange={(e) => setRunKm(e.target.value)} /></label>
            <label className="field">Run climbing (m)<input type="number" step="50" value={runElev} onChange={(e) => setRunElev(e.target.value)} /></label>
          </>}
        </div>
        <div className="fields">
          <label className="field">Hours per week at most<input type="number" step="0.5" min="3" max="22" value={maxHours} onChange={(e) => setMaxHours(e.target.value)} /></label>
          <label className="field">Weekday time
            <select value={slot} onChange={(e) => setSlot(e.target.value)}>
              <option value="morning">Morning (06:00–08:30)</option>
              <option value="midday">Midday (11:30–14:00)</option>
              <option value="afternoon">Afternoon (15:00–17:30)</option>
              <option value="evening">Evening (17:30–20:30)</option>
              <option value="flexible">Flexible</option>
            </select>
          </label>
        </div>
        <label className="row small" style={{ gap: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={useAi} disabled={!aiConfigured} onChange={(e) => setUseAi(e.target.checked)} />
          <span>Let the AI coach write the sessions as the weeks come up {!aiConfigured && <Link to="/settings/training" className="muted">(add a Gemini key first)</Link>}</span>
        </label>
        <div><button className="primary" disabled={create.isPending} onClick={() => create.mutate()}><IconPlus size={ICON.button} />{create.isPending ? "Building plan…" : "Create plan"}</button></div>
      </div>
    </Card>
  );
}

// ── race prediction ───────────────────────────────────────────────────────────
function RaceCard({ pred, plan }: { pred: any; plan: any }) {
  const [open, setOpen] = useState(false);
  const sim = pred.simulated_activity;
  const target = pred.target_time_s;
  const mid = pred.race_day_trend_s;
  const delta = target && mid ? Math.round((mid - target) / 60) : null;
  const isRun = sim?.sport === "TrailRun" || sim?.sport === "Run";
  return (
    <Card title="Race day" icon={IconRace} info="A simulation of your race at the fitness you are heading for. The range is wider while most of your training load is estimated rather than measured."
      actions={sim && <button className="sm ghost" onClick={() => setOpen(!open)}>{open ? "Hide splits" : "Splits & fuelling"}<IconChevronDownSm size={ICON.button} style={{ transform: open ? "rotate(180deg)" : undefined }} /></button>}>
      <div className="stack">
        <div className="row between" style={{ alignItems: "flex-end" }}>
          <div>
            <div className="small muted">{plan.name} · {asDate(plan.event_date).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}</div>
            <div className="race-time">{pred.range_low_s ? `${hm(pred.range_low_s)} – ${hm(pred.range_high_s)}` : hm(mid)}</div>
          </div>
          {delta != null && (
            <span className={`badge ${delta <= 0 ? "good" : "warn"}`}>
              {delta <= 0 ? <IconStatusDone size={ICON.inline} /> : <IconAttention size={ICON.inline} />}
              {delta <= 0 ? `${-delta} min inside your goal` : `${delta} min slower than your ${hm(target)} goal`}
            </span>
          )}
        </div>
        {sim && (
          <div className="stats">
            <Stat icon="distance" label="Distance" value={num(sim.distance_km, 1)} unit="km" />
            <Stat icon="elevation" label="Climbing" value={`${int(sim.elevation_gain_m)}`} unit="m" />
            {isRun ? <Stat icon="speed" label="Average pace" value={pace(sim.avg_pace_s_per_km)} /> : <Stat icon="speed" label="Average speed" value={num(sim.avg_speed_kmh, 1)} unit="km/h" />}
            <Stat icon="load" label="Fuel" value={`${int(sim.estimated_carbs_g)} g`} unit="carbs" info={`About ${int(sim.estimated_calories)} kcal burned; the carbs are what to eat during the race.`} />
          </div>
        )}
        {open && sim?.splits?.length > 0 && (
          <>
            <div className="table-wrap hide-mobile">
              <table>
                <thead><tr><th>Section</th><th className="r">Distance</th><th className="r">Climb</th><th className="r">Time</th><th className="r">Total</th><th className="r">Pace</th><th>Cue</th></tr></thead>
                <tbody>
                  {sim.splits.map((sp: any, i: number) => (
                    <tr key={i}>
                      <td><b>{sp.label}</b></td>
                      <td className="r">{sp.distance_km > 0 ? `${num(sp.distance_km, 1)} km` : "–"}</td>
                      <td className="r">{sp.elev_m > 0 ? `${int(sp.elev_m)} m` : "–"}</td>
                      <td className="r"><b>{hm(sp.time_s)}</b></td>
                      <td className="r muted">{hm(sp.cumulative_s)}</td>
                      <td className="r">{sp.pace_s_per_km ? pace(sp.pace_s_per_km) : sp.speed_kmh ? `${num(sp.speed_kmh, 1)} km/h` : "–"}</td>
                      <td className="muted">{sp.note || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="split-cards hide-desktop">
              {sim.splits.map((sp: any, i: number) => (
                <div key={i}>
                  <span className="small secondary">{sp.label}</span>
                  <b>{hm(sp.time_s)}</b>
                  <span className="xs muted">{sp.distance_km > 0 ? `${num(sp.distance_km, 1)} km` : ""}{sp.elev_m > 0 ? ` · ${int(sp.elev_m)} m` : ""}</span>
                  <span className="xs muted">{sp.pace_s_per_km ? pace(sp.pace_s_per_km) : ""}{sp.note ? ` · ${sp.note}` : ""}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

// ── page ──────────────────────────────────────────────────────────────────────
// ── AI coach ──────────────────────────────────────────────────────────────────
const TRIGGER_LABEL: Record<string, string> = {
  manual: "You asked", auto_sync: "After a sync", plan_created: "Plan created", ai_write: "Sessions written",
  mcp: "Via MCP", weekly_review: "Weekly review",
};
const triggerLabel = (t: string) => TRIGGER_LABEL[t] ?? (t.startsWith("skip_") ? `Skipped session (${t.slice(5).replaceAll("_", " ")})` : t.replaceAll("_", " "));
const shortDay = (iso: string) => asDate(iso).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });

/** The coach's note on a workout matched to the plan. */
function CoachNote({ text }: { text?: string | null }) {
  if (!text) return null;
  return <div className="coach-note"><IconSparkles size={ICON.inline} /><span>{text}</span></div>;
}

/** Shown while the AI coach works in the background; the page refreshes when it is done. */
function CoachWorking({ ai }: { ai: any }) {
  const c = ai?.coach;
  if (!c?.busy) return null;
  return (
    <div className="coach-working" role="status">
      <IconSparkles size={ICON.button} className="pulse" />
      <span><b>AI coach:</b> {c.current?.label ?? "Queued"}{c.queued > 0 && c.current ? ` (+${c.queued} more)` : ""}… Gemini can take a minute — this page updates by itself.</span>
    </div>
  );
}

function WeeklyReview({ r, weeks }: { r: any; weeks: any[] }) {
  if (!r) return null;
  const w = weeks.find((x) => x.start_date === r.week_start);
  const st = r.stats || {};
  const pct = st.planned_load ? Math.round((st.actual_load / st.planned_load) * 100) : null;
  return (
    <Card title={w ? `Week ${w.week_index} review` : "Weekly review"} icon={IconSparkles}
      hint={`${shortDay(r.week_start)} – ${shortDay(addDays(r.week_start, 6))}`}>
      <div className="stack" style={{ gap: 10 }}>
        <p className="review-headline">{r.headline}</p>
        <div className="row" style={{ gap: 6 }}>
          <span className="badge neutral">{st.done}/{st.planned} sessions</span>
          {pct != null && <span className="badge neutral">{pct}% of planned load</span>}
          <span className="badge neutral">{st.actual_hours} h of {st.planned_hours} h</span>
        </div>
        {r.went_well?.length > 0 && <ul className="review-list good">{r.went_well.map((t: string, i: number) => <li key={i}><IconDone size={ICON.inline} />{t}</li>)}</ul>}
        {r.watch?.length > 0 && <ul className="review-list warn">{r.watch.map((t: string, i: number) => <li key={i}><IconWarn size={ICON.inline} />{t}</li>)}</ul>}
        {r.next_week && <p className="small secondary"><b>Next week:</b> {r.next_week}</p>}
        <span className="xs muted">
          {r.model_used === "deterministic" ? "From your numbers" : "AI coach"} · {ago(r.created_at)}
          {r.ai_error && <InfoTip label="Why the AI coach didn't write this">The AI coach was unavailable ({r.ai_error}), so this review comes from the numbers alone.</InfoTip>}
        </span>
      </div>
    </Card>
  );
}

function CoachLog({ items }: { items: any[] }) {
  if (!items?.length) return null;
  return (
    <Card title="Coach log" icon={IconAdapted}>
      <details className="more">
        <summary><IconRight size={ICON.button} />{items.length} {items.length === 1 ? "entry" : "entries"}</summary>
        <div className="stack mt8" style={{ gap: 10 }}>
          {items.map((ad: any) => {
            const refused = ad.details?.rejected?.length ?? 0;
            return (
              <div key={ad.id} className="log-entry">
                <div className="row between xs muted">
                  <span className="row nowrap" style={{ gap: 4 }}>
                    {triggerLabel(ad.trigger)} · {ad.model_used === "deterministic" ? "built-in rules" : "AI coach"}
                    {ad.ai_error && <InfoTip label="Why the built-in rules were used">The AI coach was unavailable: {ad.ai_error}</InfoTip>}
                  </span>
                  <span>{new Date(ad.created_at).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
                </div>
                <div className="small" style={{ marginTop: 3 }}>{ad.summary}</div>
                {ad.details?.user_note && ad.trigger === "manual" && <div className="xs muted">Your note: “{ad.details.user_note}”</div>}
                {ad.diff?.length > 0 && (
                  <ul className="log-diff xs secondary">
                    {ad.diff.map((d: any, i: number) => (
                      <li key={i}>
                        <b>{d.after.title}</b>
                        {d.before.scheduled_date !== d.after.scheduled_date && <> · {shortDay(d.before.scheduled_date)} → {shortDay(d.after.scheduled_date)}</>}
                        {d.before.duration_min !== d.after.duration_min && <> · {d.before.duration_min} → {d.after.duration_min} min</>}
                        {d.after.status === "skipped" && <> · skipped</>}
                        {d.note && <span className="muted"> — {d.note}</span>}
                      </li>
                    ))}
                  </ul>
                )}
                {refused > 0 && (
                  <details className="xs muted">
                    <summary>{refused} proposed {refused === 1 ? "change" : "changes"} refused</summary>
                    <ul className="log-diff">{ad.details.rejected.map((r: any, i: number) => <li key={i}>{r.action ?? "change"}: {r.reason}</li>)}</ul>
                  </details>
                )}
              </div>
            );
          })}
        </div>
      </details>
    </Card>
  );
}

function PlanView() {
  const qc = useQueryClient();
  const toast = useToast();
  const savePrefs = useSavePrefs();
  const today = localIso();
  const [selectedPlanId, setSelectedPlanId] = useState<number | null>(null);
  const [showWizard, setShowWizard] = useState(false);
  const [chartMode, setChartMode] = useState<"ctl" | "time">("ctl");
  const [weekIdx, setWeekIdx] = useState<number | null>(null);
  const [selDay, setSelDay] = useState<string | null>(null);
  const [skipId, setSkipId] = useState<number | null>(null);
  const [adaptOpen, setAdaptOpen] = useState(false);
  const [adaptNote, setAdaptNote] = useState("");
  const [weekView, setWeekView] = useState<"week" | "month">("week");

  const listQ = useQuery<any>({ queryKey: ["training-plans"], queryFn: () => api("/training/plans") });
  const plans = listQ.data?.plans || [];
  const activeId = selectedPlanId ?? (plans.find((p: any) => p.status === "active") || plans[0])?.id ?? null;
  const detailQ = useQuery<any>({
    queryKey: ["training-plan", activeId], queryFn: () => api(`/training/plans/${activeId}`), enabled: activeId != null,
    // while the AI coach works in the background, follow it; one more fetch picks up its result
    refetchInterval: (q) => ((q.state.data as any)?.ai?.coach?.busy ? 4000 : false),
  });
  useEffect(() => {
    if (detailQ.data?.analytics?.current_week_index && weekIdx == null) setWeekIdx(detailQ.data.analytics.current_week_index);
  }, [detailQ.data, weekIdx]);

  const setPlan = (r: any) => qc.setQueryData(["training-plan", activeId], r.plan);
  const matchMut = useMutation({ mutationFn: () => api<any>(`/training/plans/${activeId}/match`, { method: "POST" }), onSuccess: (r) => { setPlan(r); toast(`${r.match.matched} activities matched`); }, onError: (e: Error) => toast(e.message, true) });
  const calMut = useMutation({ mutationFn: () => api<any>(`/training/plans/${activeId}/sync-calendar`, { method: "POST" }), onSuccess: (r) => { setPlan(r); toast(`Calendar: ${r.calendar.created} added, ${r.calendar.updated} updated`); }, onError: (e: Error) => toast(e.message, true) });
  const adaptMut = useMutation({
    mutationFn: () => api<any>(`/training/plans/${activeId}/adapt`, { method: "POST", body: { user_note: adaptNote, force: true } }),
    onSuccess: (r) => {
      setPlan(r); setAdaptNote(""); setAdaptOpen(false);
      toast(r.result.queued ? "The AI coach is looking at your plan — changes show up in the coach log" : r.result.summary || r.result.reason || "Plan adapted");
    },
    onError: (e: Error) => toast(e.message, true),
  });
  const sessionMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => api(`/training/sessions/${id}`, { method: "PATCH", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["training-plan", activeId] }),
    onError: (e: Error) => toast(e.message, true),
  });
  const skipMut = useMutation({
    mutationFn: ({ id, reason, severity, note }: { id: number; reason: SkipReason; severity: SkipSeverity; note: string }) =>
      api<any>(`/training/sessions/${id}/skip-adapt`, { method: "POST", body: { reason, severity, note } }),
    onSuccess: (r) => {
      setPlan(r); setSkipId(null);
      toast([r.result?.immediate_actions?.[0], r.result?.adaptation?.queued ? "The AI coach is adjusting the coming days." : r.result?.adaptation?.summary].filter(Boolean).join(" ") || "Plan adapted");
    },
    onError: (e: Error) => toast(e.message, true),
  });
  const variantMut = useMutation({
    mutationFn: ({ id, kind, minutes }: { id: number; kind: string; minutes?: number }) =>
      api<any>(`/training/sessions/${id}/variant`, { method: "POST", body: { kind, minutes } }),
    onSuccess: (r, v) => {
      setPlan(r);
      toast(v.kind === "original" ? "Back to the planned session" : v.kind === "shorter" ? `Shortened to ${v.minutes} min` : v.kind === "easier" ? "Made easier for today" : "Swapped with the next session");
    },
    onError: (e: Error) => toast(e.message, true),
  });
  const feedbackMut = useMutation({
    mutationFn: ({ id, rpe, feel }: { id: number; rpe: number | null; feel: string | null }) =>
      api<any>(`/training/sessions/${id}/feedback`, { method: "POST", body: { rpe, feel } }),
    onSuccess: (r) => {
      setPlan(r);
      toast(r.result.adjusted?.length ? `Thanks — the next ${r.result.adjusted.length} sessions were adjusted` : "Thanks — saved");
    },
    onError: (e: Error) => toast(e.message, true),
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => api(`/training/plans/${id}`, { method: "DELETE" }),
    onSuccess: () => { setSelectedPlanId(null); setWeekIdx(null); qc.invalidateQueries({ queryKey: ["training-plans"] }); toast("Plan deleted"); },
    onError: (e: Error) => toast(e.message, true),
  });

  const plan = detailQ.data;
  const aiInfo = plan?.ai || listQ.data?.ai;
  const weeks: any[] = plan?.weeks || [];
  const allSessions: any[] = useMemo(() => weeks.flatMap((w) => w.sessions || []), [weeks]);

  if (listQ.isLoading) return <Skeleton h={300} />;
  if (showWizard || !activeId) {
    return (
      <div className="stack gap16">
        {!activeId && <Empty title="No training plan yet" icon={IconTraining}>Pick a goal below — sessions start today and adapt as your activities come in.</Empty>}
        <CreatePlanWizard aiConfigured={Boolean(aiInfo?.configured)} onCancel={activeId ? () => setShowWizard(false) : undefined}
          onCreated={(id) => { setSelectedPlanId(id); setWeekIdx(null); setShowWizard(false); }} />
      </div>
    );
  }
  if (detailQ.isLoading || !plan) return <Skeleton h={300} />;

  const a = plan.analytics;
  const pred = a.prediction;
  const align = a.alignment;
  const base = a.baseline || {};
  const quality = a.data_quality;
  const verdict = VERDICT[pred.verdict] || VERDICT.on_track;
  const curWeek = weeks.find((w) => w.week_index === (weekIdx ?? a.current_week_index)) || weeks[0];
  const isCurrentWeek = curWeek?.week_index === a.current_week_index;
  const streak = a.gamification?.streak_sessions || 0;
  const badges: any[] = a.gamification?.badges || [];
  const discEntries = Object.entries(a.disciplines || {}) as [string, any][];

  // Next session: today's first open one, else the next planned.
  const open = (s: any) => s.sport !== "rest" && ["planned", "moved"].includes(s.status);
  const next = allSessions.find((s) => s.scheduled_date === today && open(s)) || allSessions.find((s) => s.scheduled_date >= today && open(s));
  const todayDone = allSessions.filter((s) => s.scheduled_date === today && ["completed", "partial"].includes(s.status));

  // Week progress: matched time vs target, with where you should be by today.
  const weekSessions: any[] = curWeek?.sessions || [];
  const weekActual = weekSessions.reduce((t, s) => t + (s.matched_activity?.moving_time_s || 0), 0);
  // Due by today = sessions on earlier days (today's session can still happen).
  const weekExpected = weekSessions.filter((s) => s.scheduled_date < today && s.sport !== "rest").reduce((t, s) => t + (s.target_duration_s || 0), 0);
  const weekDays = curWeek ? Array.from({ length: 7 }, (_, i) => addDays(curWeek.start_date, i)) : [];
  const shown = selDay ? weekSessions.filter((s) => s.scheduled_date === selDay) : weekSessions;

  const attention: { level: Severity; text: ReactNode; action?: ReactNode }[] = (pred.attention || pred.limiting_factors?.map((t: string) => ({ level: "warn", text: t, action: "adapt" })) || []).map((it: any) => ({
    level: it.level as Severity,
    text: it.text,
    action: it.action === "adapt" ? (
      <button className="sm" disabled={adaptMut.isPending} onClick={() => setAdaptOpen(true)}><IconAdapt size={ICON.button} />Adapt the next 14 days</button>
    ) : it.action === "profile" ? (
      quality?.suggestions?.hr_max ? (
        <div className="row">
          <button className="sm" onClick={() => savePrefs.mutate({ profile: { hr_max: quality.suggestions.hr_max } })}>Use {quality.suggestions.hr_max} bpm as max heart rate</button>
          <Link to="/settings/profile" className="small">Open profile</Link>
        </div>
      ) : <Link to="/settings/profile" className="btn sm">Open profile</Link>
    ) : undefined,
  }));

  const openSession = (s: any) => ["planned", "moved", "missed"].includes(s.status) && !s.matched_activity;
  const sessionActions = (s: any) => (
    <Menu>
      {s.status !== "completed" && <button onClick={() => sessionMut.mutate({ id: s.id, body: { status: "completed" } })}><IconStatusDone size={ICON.button} />Mark as done</button>}
      {openSession(s) && <>
        {s.changed && <button onClick={() => variantMut.mutate({ id: s.id, kind: "original" })}><IconUndo size={ICON.button} />Back to the plan</button>}
        <button onClick={() => variantMut.mutate({ id: s.id, kind: "shorter", minutes: Math.max(20, Math.round((s.target_duration_s || 3600) / 60 * 0.6)) })}><IconTime size={ICON.button} />Shorter (about 60%)</button>
        {s.session_type !== "easy" && s.session_type !== "recovery" && <button onClick={() => variantMut.mutate({ id: s.id, kind: "easier" })}><IconTired size={ICON.button} />Easier</button>}
        <button onClick={() => variantMut.mutate({ id: s.id, kind: "swap" })}><IconSync size={ICON.button} />Swap with next</button>
        <button onClick={() => setSkipId(s.id)}><IconStatusSkipped size={ICON.button} />Skip and adapt…</button>
      </>}
    </Menu>
  );
  const zones = plan.zones;

  return (
    <div className="stack gap16">
      {/* 1. Plan status: three numbers that matter, everything else behind "explain" */}
      <Card>
        <div className="plan-head">
          <div className="row between nowrap" style={{ alignItems: "flex-start" }}>
            <div className="stack" style={{ gap: 6, minWidth: 0 }}>
              <div className="title-row">
                <PlanSportIcon sport={plan.plan_type} size={ICON.header} className="muted" />
                <h2 className="ellipsis">{plan.name}</h2>
              </div>
              <div className="row" style={{ gap: 6 }}>
                <StatusBadge status={verdict.status} label={verdict.label} />
                <span className="badge neutral">{PHASE_LABEL[a.current_phase] ?? a.current_phase} · week {a.current_week_index} of {weeks.length}</span>
                {streak > 0 && <span className="badge neutral"><IconStreak size={ICON.inline} />{streak} in a row</span>}
              </div>
            </div>
            <Menu label="Plan actions">
              <button onClick={() => setAdaptOpen(true)}><IconAdapt size={ICON.button} />Adapt the next 14 days…</button>
              <button disabled={matchMut.isPending} onClick={() => matchMut.mutate()}><IconSync size={ICON.button} />Match activities now</button>
              <button disabled={calMut.isPending} onClick={() => calMut.mutate()}><IconCalendarAdd size={ICON.button} />Update calendar</button>
              <div className="sep" />
              {plans.length > 1 && plans.filter((p: any) => p.id !== plan.id).map((p: any) => (
                <button key={p.id} onClick={() => { setSelectedPlanId(p.id); setWeekIdx(null); setSelDay(null); }}><PlanSportIcon sport={p.plan_type} size={ICON.button} />Open {p.name}</button>
              ))}
              <button onClick={() => setShowWizard(true)}><IconPlus size={ICON.button} />New plan</button>
              <div className="sep" />
              {aiInfo?.configured && <div className="meta">AI coach this month: ${num(aiInfo.usage?.spent_usd ?? 0, 2)} of ${num(aiInfo.monthly_budget_usd ?? 8, 0)}</div>}
              <button className="danger" onClick={() => confirm(`Delete “${plan.name}” and all its sessions?`) && deleteMut.mutate(plan.id)}><IconTrash size={ICON.button} />Delete plan</button>
            </Menu>
          </div>
          <div className="plan-kpis">
            <div>
              <span className="k-label">Race in</span>
              <div className="k-value">{a.days_to_race >= 0 ? `${a.days_to_race} days` : "Done"}</div>
              <span className="k-sub">{asDate(plan.event_date).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</span>
            </div>
            <div>
              <span className="k-label">Predicted finish<InfoTip>Range at the fitness you are heading for. It narrows as more of your load is measured with heart rate or power.</InfoTip></span>
              <div className="k-value">{pred.range_low_s ? `${hm(pred.range_low_s)}–${hm(pred.range_high_s)}` : hm(pred.race_day_trend_s)}</div>
              <span className="k-sub">{pred.target_time_s ? `goal ${hm(pred.target_time_s)}` : "no goal time set"}</span>
            </div>
            <div>
              <span className="k-label">Plan adherence<InfoTip>Share of due sessions done, load and intensity matched, key sessions hit. Shown after a few sessions.</InfoTip></span>
              <div className="k-value">{align.enough_data ? `${Math.round(align.overall)}%` : "–"}</div>
              <span className="k-sub">{align.enough_data ? `${align.due_sessions} sessions so far` : "not enough sessions yet"}</span>
            </div>
            <div>
              <span className="k-label">Fitness</span>
              <div className="k-value">{base.readiness_label || "–"}</div>
              <span className="k-sub">{base.days_since_last_activity == null ? "no recent activity" : base.days_since_last_activity === 0 ? "trained today" : `last activity ${base.days_since_last_activity} d ago`}</span>
            </div>
          </div>
          <details className="more">
            <summary><IconRight size={ICON.button} />Explain these numbers</summary>
            <div className="stack mt8" style={{ gap: 10 }}>
              {plan.coach_summary && <p className="small secondary">{plan.coach_summary}</p>}
              <dl className="kv">
                {align.enough_data && <>
                  <dt>Sessions done</dt><dd>{Math.round(align.completion)}%</dd>
                  <dt>Load matched</dt><dd>{Math.round(align.load)}%</dd>
                  <dt>Intensity matched</dt><dd>{Math.round(align.intensity)}%</dd>
                  <dt>Key sessions hit</dt><dd>{Math.round(align.key_sessions)}%</dd>
                </>}
                <dt>Fitness / fatigue / form</dt><dd>{base.ctl} / {base.atl} / {base.tsb}</dd>
                {base.acwr != null && <><dt>Load ramp (ACWR)</dt><dd>{base.acwr}</dd></>}
                {base.detraining_factor != null && base.detraining_factor < 0.995 && <><dt>Fitness kept since last activity</dt><dd>{Math.round(base.detraining_factor * 100)}%</dd></>}
                {quality && <><dt>Load measured, not estimated</dt><dd>{Math.round(quality.measured_share * 100)}% of {quality.activities}</dd></>}
                <dt>Prediction confidence</dt><dd>{base.confidence_pct}% · ±{pred.range_pct}%</dd>
              </dl>
              {base.readiness_note && <p className="small muted">{base.readiness_note}</p>}
              {badges.length > 0 && (
                <div className="row" style={{ gap: 6 }}>
                  {badges.map((b) => { const I = KEYED_ICON[b.icon]; return <span key={b.id} className="badge neutral">{I && <I size={ICON.inline} />}{b.label}</span>; })}
                </div>
              )}
            </div>
          </details>
        </div>
      </Card>

      {adaptOpen && (
        <Card title="Adapt the next 14 days" icon={IconAdapt} actions={<button className="sm ghost" onClick={() => setAdaptOpen(false)}>Cancel</button>}>
          <div className="stack">
            <input autoFocus placeholder="Anything the coach should know? e.g. “legs heavy”, “busy Thursday evening”" value={adaptNote} onChange={(e) => setAdaptNote(e.target.value)} />
            <div className="row">
              <button className="primary sm" disabled={adaptMut.isPending} onClick={() => adaptMut.mutate()}><IconAdapt size={ICON.button} />{adaptMut.isPending ? "Adapting…" : "Adapt plan"}</button>
              {!aiInfo?.configured || !plan.ai_coach
                ? <span className="xs muted">The built-in rules adapt the plan right away.</span>
                : aiInfo.status?.last_ok === false
                  ? <span className="xs muted">Gemini didn't answer last time ({ago(aiInfo.status.last_error_at)}); if it still doesn't, the built-in rules adapt the plan.</span>
                  : <span className="xs muted">The AI coach takes up to two minutes (the built-in rules step in if Gemini is busy); you can leave this page.</span>}
            </div>
          </div>
        </Card>
      )}

      <CoachWorking ai={aiInfo} />
      {aiInfo?.configured && plan.ai_coach && aiInfo.paused_until && (
        <Callout kind="warn">Your Gemini key's daily limit is used up, so the AI coach is paused until {new Date(aiInfo.paused_until).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" })}. The built-in rules keep the plan up to date meanwhile. <Link to="/settings/training">AI coach settings</Link></Callout>
      )}
      {aiInfo?.configured && plan.ai_coach && !aiInfo.paused_until && aiInfo.status?.last_ok === false && !aiInfo.coach?.busy && (
        <Callout kind="warn">The AI coach isn't reaching Gemini ({aiInfo.status.last_error}). The built-in rules keep the plan up to date meanwhile. <Link to="/settings/training">Check the AI coach settings</Link></Callout>
      )}
      <Attention items={attention} />

      <div className="training-grid">
        <div className="stack gap16">
          {/* 2. Today first */}
          <Card title={next && next.scheduled_date === today ? "Today" : "Next session"} icon={IconTime}>
            {todayDone.length > 0 && todayDone.map((s) => (
              <div key={s.id} className="stack" style={{ gap: 6, marginBottom: 12 }}>
                <span className="row small"><StatusBadge status="completed" label="Done today" />{s.title}</span>
                {s.matched_activity && <LinkedActivity a={s.matched_activity} compliance={s.compliance_score} />}
                <CoachNote text={s.coach_feedback} />
                <Feedback s={s} busy={feedbackMut.isPending} onSave={(rpe, feel) => feedbackMut.mutate({ id: s.id, rpe, feel })} />
              </div>
            ))}
            {next ? (
              <div className="today-card">
                <PlanSportBadge sport={next.session_type === "recovery" ? "recovery" : next.sport} size={48} />
                <div style={{ minWidth: 0 }}>
                  <div className="session-when">
                    <b>{dayLabel(next.scheduled_date, today)}</b>
                    {timeSlot(next) && <span>· {timeSlot(next)}</span>}
                    {next.gcal_event_id && <span className="row nowrap" style={{ gap: 3 }}>· <IconCalendarSynced size={ICON.inline} />in calendar</span>}
                  </div>
                  <h3 className="row" style={{ gap: 6 }}>{next.title}{next.priority === "key" && <span className="badge outline"><IconKeySession size={ICON.inline} />Key</span>}</h3>
                  <SessionMetrics s={next} />
                  <Targets s={next} zones={zones} />
                  {next.description && <p className="small secondary mt8">{next.description}</p>}
                  {next.workout_steps?.length > 0 && <ul className="steps-list small secondary" style={{ margin: "6px 0 0 18px", padding: 0 }}>{next.workout_steps.map((st: string, i: number) => <li key={i}>{annotate(st, zones, next.sport)}</li>)}</ul>}
                  <WhyLine text={next.why} />
                  {next.adaptation_note && <div className="note"><IconAdapted size={ICON.inline} />{next.adaptation_note}</div>}
                  <div className="today-actions">
                    <SessionOptions s={next} busy={variantMut.isPending} onVariant={(kind, minutes) => variantMut.mutate({ id: next.id, kind, minutes })} onSkip={() => setSkipId(skipId === next.id ? null : next.id)} />
                  </div>
                  <p className="xs muted mt8">Your recorded activity from Strava or Komoot is matched automatically — then tell us how it felt.</p>
                  {skipId === next.id && <SkipDrawer busy={skipMut.isPending} onCancel={() => setSkipId(null)} onApply={(reason, severity, note) => skipMut.mutate({ id: next.id, reason, severity, note })} />}
                </div>
              </div>
            ) : <Empty title="Nothing planned" icon={IconRace}>The plan has no open sessions left.</Empty>}
          </Card>

          {/* 3. The week */}
          {curWeek && (
            <Card title={weekView === "month" ? "Calendar" : `Week ${curWeek.week_index} · ${PHASE_LABEL[curWeek.phase] ?? curWeek.phase}`}
              icon={weekView === "month" ? IconCalendarStat : undefined}
              hint={weekView === "month" ? "Planned vs done; tap a day to open its week" : curWeek.coach_focus}
              actions={
                <div className="row nowrap" style={{ gap: 4 }}>
                  {weekView === "week" && <>
                    <button className="ghost icon sm" aria-label="Previous week" disabled={curWeek.week_index <= 1} onClick={() => { setWeekIdx(curWeek.week_index - 1); setSelDay(null); }}><IconLeft size={ICON.button} /></button>
                    {!isCurrentWeek && <button className="sm ghost" onClick={() => { setWeekIdx(a.current_week_index); setSelDay(null); }}>Now</button>}
                    <button className="ghost icon sm" aria-label="Next week" disabled={curWeek.week_index >= weeks.length} onClick={() => { setWeekIdx(curWeek.week_index + 1); setSelDay(null); }}><IconRight size={ICON.button} /></button>
                  </>}
                  <Seg value={weekView} onChange={setWeekView} options={[{ value: "week", label: "Week" }, { value: "month", label: "Month" }]} />
                </div>
              }>
              {weekView === "month" ? (
                <MonthView sessions={allSessions} today={today} onPick={(d) => {
                  const w = weeks.find((x) => x.start_date <= d && d <= addDays(x.start_date, 6));
                  if (w) { setWeekIdx(w.week_index); setSelDay(d); setWeekView("week"); }
                }} />
              ) : (
              <div className="stack">
                <div className="week-strip" role="group" aria-label="Days of the week">
                  {weekDays.map((d) => {
                    const ss = weekSessions.filter((s) => s.scheduled_date === d && s.sport !== "rest");
                    return (
                      <button key={d} className={`${d === today ? "today" : ""} ${selDay === d ? "sel" : ""}`} onClick={() => setSelDay(selDay === d ? null : d)}
                        aria-label={`${asDate(d).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}: ${ss.length ? ss.map((s) => `${s.title} (${SESSION_STATUS[s.status]?.label ?? s.status})`).join(", ") : "rest"}`}>
                        <span className="wd">{asDate(d).toLocaleDateString(undefined, { weekday: "narrow" })}</span>
                        <span className="dn">{asDate(d).getDate()}</span>
                        <span className="marks">
                          {ss.map((s) => <ComplianceMark key={s.id} level={s.compliance_level} sport={s.sport} />)}
                        </span>
                      </button>
                    );
                  })}
                </div>
                <ProgressBar value={weekActual} max={curWeek.target_duration_s || 1} expected={isCurrentWeek ? weekExpected : null}
                  label={`${weekActual > 0 ? hm(weekActual) : "0m"} of ${hm(curWeek.target_duration_s)} this week`}
                  right={isCurrentWeek && weekExpected > weekActual + 600 ? `${hm(weekExpected - weekActual)} behind` : `${num(curWeek.target_distance_km, 0)} km · ${int(curWeek.target_elev_m)} m planned`} />
                <div className="stack" style={{ gap: 8 }}>
                  {shown.filter((s) => s.sport !== "rest").map((s) => {
                    const st = SESSION_STATUS[s.status] || SESSION_STATUS.planned;
                    const cmp = COMPLIANCE[s.compliance_level] ?? COMPLIANCE.planned;
                    const done = Boolean(s.matched_activity) || ["completed", "partial"].includes(s.status);
                    return (
                      <div key={s.id} className={`session ${s.scheduled_date === today ? "is-today" : ""}`} style={{ "--st": cmp.color } as React.CSSProperties}>
                        <div className="session-head">
                          <PlanSportBadge sport={s.session_type === "recovery" ? "recovery" : s.sport} size={36} />
                          <div className="grow">
                            <span className="session-when"><b>{dayLabel(s.scheduled_date, today)}</b>{timeSlot(s) && <span>· {timeSlot(s)}</span>}{s.gcal_event_id && <IconCalendarSynced size={ICON.inline} aria-label="In your calendar" />}</span>
                            <span className="session-title">{s.title}{s.priority === "key" && <span className="badge outline"><IconKeySession size={ICON.inline} />Key</span>}</span>
                            <div className="row" style={{ gap: 6 }}>
                              {s.compliance_level !== "planned"
                                ? <span className="badge neutral" style={{ color: "var(--text-primary)" }}><cmp.icon size={ICON.inline} style={{ color: cmp.color }} />{cmp.label}</span>
                                : <StatusBadge status={st.status} label={st.label} />}
                              <span className="xs muted">{SPORT_LABEL[s.sport] ?? s.sport}</span>
                            </div>
                          </div>
                          {sessionActions(s)}
                        </div>
                        <SessionMetrics s={s} />
                        {!done && <Targets s={s} zones={zones} />}
                        {s.matched_activity && <LinkedActivity a={s.matched_activity} compliance={s.compliance_score} />}
                        <CoachNote text={s.coach_feedback} />
                        {done && <Feedback s={s} busy={feedbackMut.isPending} onSave={(rpe, feel) => feedbackMut.mutate({ id: s.id, rpe, feel })} />}
                        {s.adaptation_note && <div className="note"><IconAdapted size={ICON.inline} />{s.adaptation_note}</div>}
                        {(s.description || s.workout_steps?.length > 0 || s.why) && (
                          <details className="more mt8">
                            <summary><IconRight size={ICON.button} />Workout</summary>
                            {s.description && <p className="small secondary mt8">{s.description}</p>}
                            {s.workout_steps?.length > 0 && <ul className="steps-list">{s.workout_steps.map((x: string, i: number) => <li key={i}>{annotate(x, zones, s.sport)}</li>)}</ul>}
                            <WhyLine text={s.why} />
                          </details>
                        )}
                        {skipId === s.id && s.id !== next?.id && <SkipDrawer busy={skipMut.isPending} onCancel={() => setSkipId(null)} onApply={(reason, severity, note) => skipMut.mutate({ id: s.id, reason, severity, note })} />}
                      </div>
                    );
                  })}
                  {shown.filter((s) => s.sport !== "rest").length === 0 && <p className="small muted">Rest day.</p>}
                </div>
              </div>
              )}
            </Card>
          )}
        </div>

        <div className="stack gap16">
          <WeeklyReview r={plan.weekly_review} weeks={weeks} />
          <RaceCard pred={pred} plan={plan} />
          <Card title="Where you are heading" icon={MetricIcon.load}
            info="Fitness (CTL) is your 6-week training load. Solid: what happened. Dashed black: where your current consistency leads. Grey: following the plan fully."
            actions={<Seg value={chartMode} onChange={setChartMode} options={[{ value: "ctl", label: "Fitness" }, { value: "time", label: "Finish time" }]} />}>
            <TrajectoryChart trajectory={a.trajectory || []} targetTimeS={pred.target_time_s} rangePct={pred.range_pct ?? 7} mode={chartMode} />
          </Card>
          {discEntries.length > 1 && (
            <Card title="Discipline balance" icon={IconTraining}>
              <div className="stack">
                {discEntries.map(([disc, d]) => {
                  const due = allSessions.filter((s) => (s.sport === disc || (disc === "run" && s.sport === "trail_run")) && s.scheduled_date < today).reduce((t, s) => t + (s.target_duration_s || 0) / 3600, 0);
                  return (
                    <div key={disc}>
                      <div className="row between small" style={{ marginBottom: 6 }}>
                        <span className="row nowrap" style={{ gap: 6 }}><PlanSportIcon sport={disc} size={ICON.button} style={{ color: planSportColor(disc) }} /><b>{SPORT_LABEL[disc] ?? disc}</b></span>
                        <span className="muted">{d.completed_sessions}/{d.planned_sessions} sessions</span>
                      </div>
                      <ProgressBar value={d.actual_hours} max={d.planned_hours || 1} expected={due} color={planSportColor(disc)} label={`${d.actual_hours} h of ${d.planned_hours} h`} />
                    </div>
                  );
                })}
              </div>
            </Card>
          )}
          <CoachLog items={plan.adaptations} />
        </div>
      </div>
    </div>
  );
}

export default function Training() {
  const { view = "plan" } = useParams();
  const nav = useNavigate();
  return (
    <>
      <div className="page-head">
        <div><h1>Training</h1><div className="sub static">Your plan, adapted to what you actually record</div></div>
      </div>
      <Tabs value={view === "race" ? "race" : "plan"} onChange={(v) => nav(v === "plan" ? "/training" : `/training/${v}`)}
        tabs={[{ value: "plan", label: <><IconTraining size={ICON.button} />Plan</> }, { value: "race", label: <><IconRace size={ICON.button} />Race tools</> }]} />
      {view === "race" ? <TrailTab /> : <PlanView />}
    </>
  );
}
