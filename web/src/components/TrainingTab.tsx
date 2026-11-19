import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { duration, int, num } from "../lib/format";
import { Callout, Card, Empty, Seg, Skeleton, Stat, useToast } from "./ui";
import { TrailTab } from "./TrailTab";

type PlanType = "trail_run" | "road_run" | "cycling" | "triathlon" | "duathlon" | "base_build";

const PLAN_TYPE_LABELS: Record<PlanType, string> = {
  trail_run: "Trail Run",
  road_run: "Road Run",
  cycling: "Cycling",
  triathlon: "Triathlon",
  duathlon: "Duathlon",
  base_build: "Base Build",
};

const PHASE_TONE: Record<string, string> = {
  base: "",
  build: "good",
  peak: "warn",
  recovery: "",
  taper: "good",
  race_week: "bad",
};

const VERDICT_META: Record<string, { label: string; cls: string }> = {
  on_track: { label: "On Track", cls: "good" },
  catchable: { label: "Slightly Behind (Catchable)", cls: "warn" },
  at_risk: { label: "At Risk", cls: "bad" },
};

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  completed: { label: "Done", cls: "good" },
  partial: { label: "Partial", cls: "warn" },
  missed: { label: "Missed", cls: "bad" },
  moved: { label: "Moved", cls: "warn" },
  skipped: { label: "Skipped", cls: "" },
  planned: { label: "Planned", cls: "" },
};

function fmtTimeHms(sec: number | null | undefined): string {
  if (sec == null || sec <= 0) return "—";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

function parseHmToSec(hm: string): number | null {
  const s = hm.trim();
  if (!s) return null;
  const parts = s.split(":").map((x) => Number(x));
  if (parts.some((x) => Number.isNaN(x))) return null;
  if (parts.length === 2) return parts[0] * 3600 + parts[1] * 60;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return null;
}

function addDaysIso(isoDate: string, days: number): string {
  const d = new Date(`${isoDate}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Interactive SVG Development & Prediction Trajectory Graph (CTL or Predicted Finish Time). */
function TrajectoryChart({
  trajectory,
  targetTimeS,
  mode,
}: {
  trajectory: any[];
  targetTimeS: number | null;
  mode: "ctl" | "time";
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(ref.current);
    setWidth(Math.floor(ref.current.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, []);

  if (!trajectory.length) return <Empty title="No trajectory data" />;

  const height = 240;
  const padL = 52;
  const padR = 16;
  const padT = 16;
  const padB = 28;
  const innerW = Math.max(width - padL - padR, 40);
  const innerH = height - padT - padB;
  const n = trajectory.length;
  const xOf = (i: number) => padL + (n === 1 ? innerW / 2 : (i / (n - 1)) * innerW);

  const todayIdx = trajectory.reduce((acc, pt, i) => (!pt.is_future ? i : acc), 0);

  let minV = 0;
  let maxV = 100;
  if (mode === "ctl") {
    const vals = trajectory.flatMap((p) =>
      [p.actual_ctl, p.planned_ctl, p.projected_ctl_optimal, p.projected_ctl_trend].filter((v) => v != null),
    );
    minV = Math.max(0, Math.floor((Math.min(...vals, 0) - 5) / 5) * 5);
    maxV = Math.ceil((Math.max(...vals, 20) + 8) / 5) * 5;
  } else {
    const vals = trajectory.map((p) => p.predicted_time_s).filter((v) => v > 0);
    if (targetTimeS) vals.push(targetTimeS);
    minV = Math.max(600, Math.min(...vals) * 0.94);
    maxV = Math.max(...vals) * 1.06;
  }
  const span = Math.max(1, maxV - minV);
  const yOf = (v: number) => padT + innerH - ((v - minV) / span) * innerH;

  const pathFor = (pts: [number, number][]) =>
    pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => minV + f * span);
  const hoverPt = hoverIdx != null ? trajectory[hoverIdx] : null;

  // Build SVG paths
  const plannedPts: [number, number][] = trajectory.map((p, i) => [xOf(i), yOf(p.planned_ctl)]);
  const actualPts: [number, number][] = trajectory
    .map((p, i) => (p.actual_ctl != null ? ([xOf(i), yOf(p.actual_ctl)] as [number, number]) : null))
    .filter(Boolean) as [number, number][];
  const optPts: [number, number][] = trajectory
    .slice(todayIdx)
    .map((p, k) => [xOf(todayIdx + k), yOf(p.projected_ctl_optimal)]);
  const trendPts: [number, number][] = trajectory
    .slice(todayIdx)
    .map((p, k) => [xOf(todayIdx + k), yOf(p.projected_ctl_trend)]);

  const conePath =
    optPts.length >= 2 && trendPts.length >= 2
      ? `${pathFor(optPts)} L${[...trendPts].reverse().map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" L")} Z`
      : "";

  const timePts: [number, number][] = trajectory.map((p, i) => [xOf(i), yOf(p.predicted_time_s)]);

  return (
    <div className="chart" ref={ref} onMouseLeave={() => setHoverIdx(null)}>
      {width > 0 && (
        <svg width={width} height={height}>
          {ticks.map((t, i) => {
            const y = yOf(t);
            return (
              <g key={i}>
                <line className="gridline" x1={padL} x2={width - padR} y1={y} y2={y} />
                <text x={padL - 6} y={y + 4} textAnchor="end">
                  {mode === "ctl" ? Math.round(t) : fmtTimeHms(t)}
                </text>
              </g>
            );
          })}

          {/* Today marker */}
          <line
            x1={xOf(todayIdx)}
            x2={xOf(todayIdx)}
            y1={padT}
            y2={padT + innerH}
            stroke="var(--ink-3)"
            strokeDasharray="3 3"
            opacity={0.7}
          />
          <text x={xOf(todayIdx)} y={padT - 4} textAnchor="middle" fontSize="10" fill="var(--ink-3)">
            Today
          </text>

          {mode === "ctl" ? (
            <>
              {conePath && <path d={conePath} fill="var(--accent)" opacity={0.14} />}
              <path d={pathFor(plannedPts)} fill="none" stroke="var(--ink-3)" strokeWidth={1.6} strokeDasharray="5 4" />
              {optPts.length >= 2 && (
                <path d={pathFor(optPts)} fill="none" stroke="var(--good)" strokeWidth={2} strokeDasharray="4 3" />
              )}
              {trendPts.length >= 2 && (
                <path d={pathFor(trendPts)} fill="none" stroke="var(--warn)" strokeWidth={2.2} />
              )}
              {actualPts.length >= 1 && (
                <path d={pathFor(actualPts)} fill="none" stroke="var(--accent)" strokeWidth={2.6} />
              )}
            </>
          ) : (
            <>
              {targetTimeS && (
                <>
                  <line
                    x1={padL}
                    x2={width - padR}
                    y1={yOf(targetTimeS)}
                    y2={yOf(targetTimeS)}
                    stroke="var(--good)"
                    strokeWidth={1.8}
                    strokeDasharray="6 4"
                  />
                  <text x={width - padR} y={yOf(targetTimeS) - 5} textAnchor="end" fontSize="10" fill="var(--good)">
                    Goal {fmtTimeHms(targetTimeS)}
                  </text>
                </>
              )}
              <path d={pathFor(timePts)} fill="none" stroke="var(--accent)" strokeWidth={2.5} />
            </>
          )}

          {/* X-axis labels */}
          {trajectory.map((p, i) => {
            const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(innerW / 64))));
            if (i % every !== 0 && i !== n - 1) return null;
            return (
              <text key={p.week_index} x={xOf(i)} y={height - 6} textAnchor="middle">
                W{p.week_index}
              </text>
            );
          })}

          {/* Hover capture columns */}
          {trajectory.map((p, i) => {
            const colW = innerW / Math.max(1, n);
            return (
              <rect
                key={p.week_index}
                x={Math.max(padL, xOf(i) - colW / 2)}
                y={padT}
                width={colW}
                height={innerH}
                fill="transparent"
                onMouseEnter={() => setHoverIdx(i)}
                onClick={() => setHoverIdx(i)}
              />
            );
          })}

          {hoverIdx != null && (
            <line
              x1={xOf(hoverIdx)}
              x2={xOf(hoverIdx)}
              y1={padT}
              y2={padT + innerH}
              stroke="var(--accent)"
              strokeWidth={1}
              opacity={0.5}
            />
          )}
        </svg>
      )}

      {hoverPt && width > 0 && (
        <div
          className="tooltip"
          style={{
            left: Math.min(Math.max(xOf(hoverIdx!) + 10, 8), Math.max(width - 210, 8)),
            top: 12,
          }}
        >
          <div style={{ fontWeight: 600 }}>
            Week {hoverPt.week_index} · {hoverPt.phase.replace("_", " ")}
          </div>
          <div className="xs muted">{hoverPt.date}</div>
          {mode === "ctl" ? (
            <div className="xs" style={{ marginTop: 4 }}>
              {hoverPt.actual_ctl != null && <div>Actual CTL: <b>{hoverPt.actual_ctl}</b></div>}
              <div>Planned CTL: <b>{hoverPt.planned_ctl}</b></div>
              {hoverPt.is_future && (
                <>
                  <div>Optimal (100%): <b>{hoverPt.projected_ctl_optimal}</b></div>
                  <div>Current Trend: <b>{hoverPt.projected_ctl_trend}</b></div>
                </>
              )}
            </div>
          ) : (
            <div className="xs" style={{ marginTop: 4 }}>
              <div>Predicted: <b>{fmtTimeHms(hoverPt.predicted_time_s)}</b></div>
              {targetTimeS && <div>Goal: <b>{fmtTimeHms(targetTimeS)}</b></div>}
            </div>
          )}
        </div>
      )}

      <div className="row mt8 xs muted" style={{ gap: 14, flexWrap: "wrap" }}>
        {mode === "ctl" ? (
          <>
            <span><b style={{ color: "var(--accent)" }}>━━</b> Actual CTL</span>
            <span><b style={{ color: "var(--ink-3)" }}>┄┄</b> Planned CTL</span>
            <span><b style={{ color: "var(--good)" }}>┄┄</b> Projected (100% plan)</span>
            <span><b style={{ color: "var(--warn)" }}>━━</b> Projected (current trend)</span>
          </>
        ) : (
          <>
            <span><b style={{ color: "var(--accent)" }}>━━</b> Predicted finish time</span>
            {targetTimeS && <span><b style={{ color: "var(--good)" }}>┄┄</b> Target goal time</span>}
          </>
        )}
      </div>
    </div>
  );
}

/** Plan Creation Wizard */
function CreatePlanWizard({
  onCreated,
  onCancel,
  aiConfigured,
}: {
  onCreated: (planId: number) => void;
  onCancel?: () => void;
  aiConfigured: boolean;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const defaultDate = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() + 84);
    return d.toISOString().slice(0, 10);
  }, []);

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

  const onTypeChange = (t: PlanType) => {
    setPlanType(t);
    if (t === "trail_run") {
      setName("50k Trail Race");
      setRunKm("50");
      setRunElev("2200");
    } else if (t === "road_run") {
      setName("Half Marathon");
      setRunKm("21.1");
      setRunElev("100");
    } else if (t === "cycling") {
      setName("Gran Fondo 140k");
      setBikeKm("140");
      setBikeElev("2200");
    } else if (t === "triathlon") {
      setName("70.3 Triathlon");
      setSwimKm("1.9");
      setBikeKm("90");
      setBikeElev("900");
      setRunKm("21.1");
      setRunElev("150");
    } else if (t === "duathlon") {
      setName("Long Duathlon");
      setBikeKm("60");
      setBikeElev("600");
      setRunKm("15");
      setRunElev("100");
    } else {
      setName("Multi-Sport Base Build");
    }
  };

  const create = useMutation({
    mutationFn: () => {
      const targets: Record<string, number> = {};
      if (planType === "trail_run" || planType === "road_run" || planType === "triathlon" || planType === "duathlon") {
        targets.run_km = Number(runKm) || 21.1;
        targets.run_elev_m = Number(runElev) || 0;
      }
      if (planType === "cycling" || planType === "triathlon" || planType === "duathlon") {
        targets.bike_km = Number(bikeKm) || 90;
        targets.bike_elev_m = Number(bikeElev) || 0;
      }
      if (planType === "triathlon") {
        targets.swim_km = Number(swimKm) || 1.9;
      }
      const targetTimeS = parseHmToSec(goalTime);
      return api<any>("/training/plans", {
        method: "POST",
        body: {
          name: name.trim() || PLAN_TYPE_LABELS[planType],
          plan_type: planType,
          event_date: eventDate,
          goal_spec: { targets, ...(targetTimeS ? { target_time_s: targetTimeS } : {}) },
          schedule_prefs: {
            max_weekly_hours: Number(maxHours) || 8,
            preferred_slot: slot,
            rest_days: [0],
          },
          use_ai: useAi,
          set_active: true,
        },
      });
    },
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["training-plans"] });
      toast(`Created ${p.name}`);
      onCreated(p.id);
    },
    onError: (e: Error) => toast(e.message, true),
  });

  const showRun = planType === "trail_run" || planType === "road_run" || planType === "triathlon" || planType === "duathlon";
  const showBike = planType === "cycling" || planType === "triathlon" || planType === "duathlon";
  const showSwim = planType === "triathlon";

  return (
    <Card
      title="Create Adaptive Training Plan"
      actions={onCancel ? <button className="sm ghost" onClick={onCancel}>Cancel</button> : undefined}
    >
      <div className="stack" style={{ gap: 14 }}>
        <div>
          <div className="xs muted" style={{ marginBottom: 6 }}>Sport / Goal Type</div>
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            {(Object.keys(PLAN_TYPE_LABELS) as PlanType[]).map((t) => (
              <button
                key={t}
                type="button"
                className={planType === t ? "sm primary" : "sm"}
                onClick={() => onTypeChange(t)}
              >
                {PLAN_TYPE_LABELS[t]}
              </button>
            ))}
          </div>
        </div>

        <div className="fields">
          <label className="field">
            Goal / Race Name
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field">
            Target Date
            <input type="date" value={eventDate} onChange={(e) => setEventDate(e.target.value)} />
          </label>
          <label className="field">
            Goal Finish Time (optional, hh:mm)
            <input placeholder="e.g. 6:30" value={goalTime} onChange={(e) => setGoalTime(e.target.value)} />
          </label>
        </div>

        <div className="fields">
          {showSwim && (
            <label className="field">
              Swim Distance (km)
              <input type="number" step="0.1" value={swimKm} onChange={(e) => setSwimKm(e.target.value)} />
            </label>
          )}
          {showBike && (
            <>
              <label className="field">
                Bike Distance (km)
                <input type="number" step="1" value={bikeKm} onChange={(e) => setBikeKm(e.target.value)} />
              </label>
              <label className="field">
                Bike Elevation D+ (m)
                <input type="number" step="50" value={bikeElev} onChange={(e) => setBikeElev(e.target.value)} />
              </label>
            </>
          )}
          {showRun && (
            <>
              <label className="field">
                Run Distance (km)
                <input type="number" step="0.5" value={runKm} onChange={(e) => setRunKm(e.target.value)} />
              </label>
              <label className="field">
                Run Elevation D+ (m)
                <input type="number" step="50" value={runElev} onChange={(e) => setRunElev(e.target.value)} />
              </label>
            </>
          )}
        </div>

        <div className="fields">
          <label className="field">
            Max Weekly Hours
            <input type="number" step="0.5" min="3" max="22" value={maxHours} onChange={(e) => setMaxHours(e.target.value)} />
          </label>
          <label className="field">
            Preferred Weekday Time Slot
            <select value={slot} onChange={(e) => setSlot(e.target.value)}>
              <option value="morning">Morning (06:00–08:30)</option>
              <option value="midday">Midday (11:30–14:00)</option>
              <option value="afternoon">Afternoon (15:00–17:30)</option>
              <option value="evening">Evening (17:30–20:30)</option>
              <option value="flexible">Flexible</option>
            </select>
          </label>
        </div>

        <label className="row xs" style={{ gap: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
          <span>
            Enrich upcoming 4 weeks with <b>Gemini Pro</b>{" "}
            {!aiConfigured && <span className="muted">(configure Gemini API key in Settings to enable)</span>}
          </span>
        </label>

        <div className="row">
          <button className="primary" disabled={create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? "Generating Plan…" : "Generate Training Plan"}
          </button>
        </div>
      </div>
    </Card>
  );
}

export function TrainingTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [subView, setSubView] = useState<"plan" | "trail_tools">("plan");
  const [selectedPlanId, setSelectedPlanId] = useState<number | null>(null);
  const [showWizard, setShowWizard] = useState(false);
  const [chartMode, setChartMode] = useState<"ctl" | "time">("ctl");
  const [weekIdx, setWeekIdx] = useState<number | null>(null);
  const [adaptNote, setAdaptNote] = useState("");

  const listQ = useQuery<any>({
    queryKey: ["training-plans"],
    queryFn: () => api("/training/plans"),
  });

  const activeId = useMemo(() => {
    if (selectedPlanId) return selectedPlanId;
    const plans = listQ.data?.plans || [];
    const active = plans.find((p: any) => p.status === "active") || plans[0];
    return active ? active.id : null;
  }, [listQ.data, selectedPlanId]);

  const detailQ = useQuery<any>({
    queryKey: ["training-plan", activeId],
    queryFn: () => api(`/training/plans/${activeId}`),
    enabled: activeId != null && subView === "plan",
  });

  useEffect(() => {
    if (detailQ.data?.analytics?.current_week_index && weekIdx == null) {
      setWeekIdx(detailQ.data.analytics.current_week_index);
    }
  }, [detailQ.data, weekIdx]);

  const matchMut = useMutation({
    mutationFn: () => api<any>(`/training/plans/${activeId}/match`, { method: "POST" }),
    onSuccess: (r) => {
      qc.setQueryData(["training-plan", activeId], r.plan);
      toast(`Synced: ${r.match.matched} matched, ${r.match.missed} missed`);
    },
    onError: (e: Error) => toast(e.message, true),
  });

  const adaptMut = useMutation({
    mutationFn: () =>
      api<any>(`/training/plans/${activeId}/adapt`, {
        method: "POST",
        body: { user_note: adaptNote, force: true },
      }),
    onSuccess: (r) => {
      qc.setQueryData(["training-plan", activeId], r.plan);
      setAdaptNote("");
      toast(r.result.summary || "Plan adapted");
    },
    onError: (e: Error) => toast(e.message, true),
  });

  const sessionMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
      api(`/training/sessions/${id}`, { method: "PATCH", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["training-plan", activeId] });
    },
    onError: (e: Error) => toast(e.message, true),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api(`/training/plans/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setSelectedPlanId(null);
      setWeekIdx(null);
      qc.invalidateQueries({ queryKey: ["training-plans"] });
      toast("Plan deleted");
    },
    onError: (e: Error) => toast(e.message, true),
  });

  const plans = listQ.data?.plans || [];
  const aiInfo = detailQ.data?.ai || listQ.data?.ai;

  return (
    <div className="stack gap16">
      <div className="row between" style={{ gap: 8, flexWrap: "wrap" }}>
        <Seg
          value={subView}
          options={[
            { value: "plan", label: "Adaptive Plan & Predictions" },
            { value: "trail_tools", label: "Trail Readiness & GPX Pacer" },
          ]}
          onChange={setSubView}
        />
        {subView === "plan" && (
          <div className="row" style={{ gap: 8 }}>
            {plans.length > 1 && (
              <select
                value={activeId ?? ""}
                onChange={(e) => {
                  setSelectedPlanId(Number(e.target.value));
                  setWeekIdx(null);
                }}
              >
                {plans.map((p: any) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({PLAN_TYPE_LABELS[p.plan_type as PlanType] || p.plan_type})
                  </option>
                ))}
              </select>
            )}
            <button className="sm primary" onClick={() => setShowWizard((v) => !v)}>
              {showWizard ? "Close Wizard" : "+ New Plan"}
            </button>
          </div>
        )}
      </div>

      {subView === "trail_tools" ? (
        <TrailTab />
      ) : listQ.isLoading ? (
        <Skeleton h={220} />
      ) : showWizard || !activeId ? (
        <CreatePlanWizard
          aiConfigured={Boolean(aiInfo?.configured)}
          onCancel={activeId ? () => setShowWizard(false) : undefined}
          onCreated={(id) => {
            setSelectedPlanId(id);
            setWeekIdx(null);
            setShowWizard(false);
          }}
        />
      ) : detailQ.isLoading || !detailQ.data ? (
        <Skeleton h={260} />
      ) : (
        (() => {
          const plan = detailQ.data;
          const a = plan.analytics;
          const pred = a.prediction;
          const align = a.alignment;
          const verdict = VERDICT_META[pred.verdict] || VERDICT_META.on_track;
          const weeks: any[] = plan.weeks || [];
          const curWeek = weeks.find((w) => w.week_index === (weekIdx ?? a.current_week_index)) || weeks[0];
          const discEntries = Object.entries(a.disciplines || {}) as [string, any][];

          return (
            <>
              {/* Plan Summary & KPIs */}
              <Card
                title={
                  <span className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                    <span>{plan.name}</span>
                    <span className="badge">{PLAN_TYPE_LABELS[plan.plan_type as PlanType] || plan.plan_type}</span>
                    <span className={`badge ${PHASE_TONE[a.current_phase] || ""}`}>
                      {a.current_phase.replace("_", " ")}
                    </span>
                    <span className={`badge ${verdict.cls}`}>{verdict.label}</span>
                  </span>
                }
                actions={
                  <div className="row" style={{ gap: 6 }}>
                    {aiInfo && (
                      <span className="badge" title="Gemini monthly credit usage">
                        AI: ${num(aiInfo.usage?.spent_usd ?? 0, 2)} / ${num(aiInfo.monthly_budget_usd ?? 8, 0)}
                      </span>
                    )}
                    <button
                      className="sm ghost danger"
                      onClick={() => confirm(`Delete "${plan.name}"?`) && deleteMut.mutate(plan.id)}
                    >
                      Delete
                    </button>
                  </div>
                }
              >
                <div className="stats">
                  <Stat
                    label="Race Countdown"
                    value={a.days_to_race >= 0 ? `${a.days_to_race}d` : "Completed"}
                    unit={a.days_to_race >= 0 ? `(${a.weeks_to_race}w)` : ""}
                  />
                  <Stat label="Plan Alignment" value={`${Math.round(align.overall)}`} unit="/ 100" />
                  <Stat
                    label="Predicted Finish"
                    value={fmtTimeHms(pred.race_day_trend_s)}
                    unit={pred.target_time_s ? `vs ${fmtTimeHms(pred.target_time_s)}` : "at current trend"}
                  />
                  <Stat
                    label="Optimal (100%)"
                    value={fmtTimeHms(pred.race_day_optimal_s)}
                    unit={`CTL ${a.baseline.ctl}`}
                  />
                </div>

                {/* 4-pillar alignment mini strip */}
                <div className="row mt12 xs muted" style={{ gap: 16, flexWrap: "wrap" }}>
                  <span>Completion: <b>{Math.round(align.completion)}%</b></span>
                  <span>Load fidelity: <b>{Math.round(align.load)}%</b></span>
                  <span>Zone discipline: <b>{Math.round(align.intensity)}%</b></span>
                  <span>Key sessions: <b>{Math.round(align.key_sessions)}%</b></span>
                  {a.baseline.acwr != null && <span>ACWR: <b>{a.baseline.acwr}</b></span>}
                </div>

                {plan.coach_summary && (
                  <p className="small muted mt12" style={{ marginBottom: 0 }}>
                    {plan.coach_summary}
                  </p>
                )}

                {pred.limiting_factors?.length > 0 && (
                  <div className="stack mt12" style={{ gap: 6 }}>
                    {pred.limiting_factors.map((f: string, idx: number) => (
                      <Callout key={idx} kind={pred.verdict === "at_risk" ? "bad" : "warn"}>
                        {f}
                      </Callout>
                    ))}
                  </div>
                )}

                {pred.race_day_splits && Object.keys(pred.race_day_splits).length > 1 && (
                  <div className="row mt12 xs muted" style={{ gap: 12, flexWrap: "wrap" }}>
                    <b>Predicted Splits:</b>
                    {pred.race_day_splits.swim_s > 0 && <span>Swim {fmtTimeHms(pred.race_day_splits.swim_s)}</span>}
                    {pred.race_day_splits.bike_s > 0 && <span>Bike {fmtTimeHms(pred.race_day_splits.bike_s)}</span>}
                    {pred.race_day_splits.run_s > 0 && <span>Run {fmtTimeHms(pred.race_day_splits.run_s)}</span>}
                    {pred.race_day_splits.transitions_s > 0 && (
                      <span>T1+T2 {fmtTimeHms(pred.race_day_splits.transitions_s)}</span>
                    )}
                  </div>
                )}
              </Card>

              {/* Development & Prediction Graph */}
              <Card
                title="Development & Race Prediction"
                actions={
                  <Seg
                    value={chartMode}
                    options={[
                      { value: "ctl", label: "Fitness (CTL)" },
                      { value: "time", label: "Predicted Time" },
                    ]}
                    onChange={setChartMode}
                  />
                }
              >
                <TrajectoryChart
                  trajectory={a.trajectory || []}
                  targetTimeS={pred.target_time_s}
                  mode={chartMode}
                />
              </Card>

              {/* AI Coach Adaptation Bar */}
              <Card
                title="AI Coach Adaptation"
                actions={
                  <button className="sm" disabled={matchMut.isPending} onClick={() => matchMut.mutate()}>
                    {matchMut.isPending ? "Matching…" : "Match Activities"}
                  </button>
                }
              >
                <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                  <input
                    style={{ flex: "1 1 240px" }}
                    placeholder="Optional feedback for Gemini (e.g. 'Legs heavy today', 'Busy Thu evening')…"
                    value={adaptNote}
                    onChange={(e) => setAdaptNote(e.target.value)}
                  />
                  <button className="primary sm" disabled={adaptMut.isPending} onClick={() => adaptMut.mutate()}>
                    {adaptMut.isPending ? "Adapting…" : "Adapt Next 14 Days"}
                  </button>
                </div>
                {!aiInfo?.configured && (
                  <p className="xs muted mt8" style={{ marginBottom: 0 }}>
                    Gemini API key not configured — adaptations will use the built-in deterministic sports-science fallback until you add your key in <b>Settings → AI Coach (Gemini)</b>.
                  </p>
                )}
              </Card>

              {/* Multi-sport Discipline Balance (for Triathlon / Duathlon / Base) */}
              {discEntries.length > 1 && (
                <Card title="Multi-Sport Discipline Balance">
                  <div className="stack" style={{ gap: 10 }}>
                    {discEntries.map(([disc, d]) => {
                      const pct = d.planned_hours > 0 ? Math.min(100, Math.round((d.actual_hours / d.planned_hours) * 100)) : 0;
                      return (
                        <div key={disc}>
                          <div className="row between xs">
                            <b style={{ textTransform: "capitalize" }}>{disc}</b>
                            <span className="muted">
                              {d.actual_hours}h / {d.planned_hours}h · {d.completed_sessions}/{d.planned_sessions} sessions ({pct}%)
                            </span>
                          </div>
                          <div style={{ height: 7, borderRadius: 4, background: "var(--border)", marginTop: 4, overflow: "hidden" }}>
                            <div style={{ width: `${pct}%`, height: "100%", background: "var(--accent)", borderRadius: 4 }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </Card>
              )}

              {/* Weekly Schedule */}
              {curWeek && (
                <Card
                  title={
                    <span>
                      Week {curWeek.week_index} of {weeks.length} ·{" "}
                      <span style={{ textTransform: "capitalize" }}>{curWeek.phase.replace("_", " ")}</span>
                    </span>
                  }
                  actions={
                    <div className="row" style={{ gap: 6 }}>
                      <button
                        className="sm"
                        disabled={curWeek.week_index <= 1}
                        onClick={() => setWeekIdx(Math.max(1, curWeek.week_index - 1))}
                      >
                        ← Prev
                      </button>
                      <button
                        className="sm ghost"
                        onClick={() => setWeekIdx(a.current_week_index)}
                      >
                        Current
                      </button>
                      <button
                        className="sm"
                        disabled={curWeek.week_index >= weeks.length}
                        onClick={() => setWeekIdx(Math.min(weeks.length, curWeek.week_index + 1))}
                      >
                        Next →
                      </button>
                    </div>
                  }
                >
                  <div className="row between xs muted" style={{ marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
                    <span>{curWeek.coach_focus}</span>
                    <span>
                      Target: <b>{duration(curWeek.target_duration_s)}</b> · <b>{num(curWeek.target_distance_km, 1)} km</b> ·{" "}
                      <b>+{int(curWeek.target_elev_m)} m</b> · <b>{int(curWeek.target_tss)} TSS</b>
                    </span>
                  </div>

                  <div className="stack" style={{ gap: 10 }}>
                    {(curWeek.sessions || []).map((s: any) => {
                      const sb = STATUS_BADGE[s.status] || STATUS_BADGE.planned;
                      return (
                        <div
                          key={s.id}
                          style={{
                            border: "1px solid var(--border)",
                            borderRadius: 10,
                            padding: "10px 12px",
                            background: s.priority === "key" ? "var(--surface-2, var(--bg))" : "transparent",
                          }}
                        >
                          <div className="row between" style={{ gap: 8, flexWrap: "wrap" }}>
                            <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                              <span className="mono xs muted">{s.scheduled_date}</span>
                              <span className="badge">{s.sport.replace("_", " ")}</span>
                              {s.priority === "key" && <span className="badge warn">KEY</span>}
                              <span className={`badge ${sb.cls}`}>{sb.label}</span>
                              <b>{s.title}</b>
                            </div>
                            <div className="row" style={{ gap: 4 }}>
                              {s.status !== "completed" && (
                                <button
                                  className="sm"
                                  onClick={() => sessionMut.mutate({ id: s.id, body: { status: "completed" } })}
                                >
                                  ✓ Done
                                </button>
                              )}
                              {s.status !== "completed" && s.status !== "skipped" && (
                                <>
                                  <button
                                    className="sm ghost"
                                    title="Move 1 day forward"
                                    onClick={() =>
                                      sessionMut.mutate({
                                        id: s.id,
                                        body: { scheduled_date: addDaysIso(s.scheduled_date, 1) },
                                      })
                                    }
                                  >
                                    +1d
                                  </button>
                                  <button
                                    className="sm ghost"
                                    onClick={() => sessionMut.mutate({ id: s.id, body: { status: "skipped" } })}
                                  >
                                    Skip
                                  </button>
                                </>
                              )}
                            </div>
                          </div>

                          <div className="xs muted mt8">
                            {duration(s.target_duration_s)}
                            {s.target_distance_km > 0 && ` · ${num(s.target_distance_km, 1)} km`}
                            {s.target_elev_m > 0 && ` · +${int(s.target_elev_m)} m`}
                            {s.target_tss > 0 && ` · ${int(s.target_tss)} TSS`}
                            {s.scheduled_slot && ` · ${s.scheduled_slot}`}
                            {s.compliance_score != null && ` · Compliance ${Math.round(s.compliance_score)}%`}
                          </div>

                          {s.description && <p className="small mt8" style={{ marginBottom: 4 }}>{s.description}</p>}

                          {s.workout_steps?.length > 0 && (
                            <ul className="xs muted" style={{ margin: "4px 0 0 18px", padding: 0 }}>
                              {s.workout_steps.map((st: string, i: number) => (
                                <li key={i}>{st}</li>
                              ))}
                            </ul>
                          )}

                          {s.adaptation_note && (
                            <div className="xs mt8" style={{ color: "var(--warn)" }}>
                              Adapted: {s.adaptation_note}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </Card>
              )}

              {/* Adaptation History */}
              {plan.adaptations?.length > 0 && (
                <Card title="Coach Adaptation Log">
                  <div className="stack" style={{ gap: 8 }}>
                    {plan.adaptations.map((ad: any) => (
                      <div key={ad.id} style={{ borderBottom: "1px solid var(--border)", paddingBottom: 8 }}>
                        <div className="row between xs muted">
                          <span>
                            <b>{ad.trigger.replace("_", " ")}</b> · <span className="mono">{ad.model_used}</span>
                          </span>
                          <span>{ad.created_at?.slice(0, 16).replace("T", " ")} UTC</span>
                        </div>
                        <div className="small" style={{ marginTop: 3 }}>{ad.summary}</div>
                      </div>
                    ))}
                  </div>
                </Card>
              )}
            </>
          );
        })()
      )}
    </div>
  );
}
