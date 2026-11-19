import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { IconApi, IconImport, IconTarget, MetricIcon } from "./icons";
import { Callout, Card, Empty, Skeleton, Stat, useToast } from "./ui";
import { api } from "../lib/api";
import { duration, int, num } from "../lib/format";

const PHASE_LABEL: Record<string, [string, string]> = {
  base: ["info", "Base phase"],
  build: ["info", "Build phase"],
  peak: ["warn", "Peak block"],
  taper: ["good", "Taper"],
  race_week: ["good", "Race week"],
  completed: ["", "Completed"],
  unscheduled: ["", "No race date set"],
};

const ACWR_BADGE: Record<string, [string, string]> = {
  optimal: ["good", "Optimal (0.8–1.3)"],
  low: ["info", "Low (<0.8)"],
  caution: ["warn", "Caution (1.3–1.5)"],
  high_risk: ["bad", "High risk (>1.5)"],
  unknown: ["", "Building baseline"],
};

export function TrailTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isLoading } = useQuery<any>({
    queryKey: ["trail-readiness"],
    queryFn: () => api("/insights/trail", { params: { weeks: 8 } }),
  });

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<any>(null);

  const saveGoal = useMutation({
    mutationFn: (trail_race: any) => api("/settings", { method: "PATCH", body: { trail_race } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["trail-readiness"] });
      qc.invalidateQueries({ queryKey: ["settings"] });
      setEditing(false);
      toast("Trail race target saved");
    },
    onError: (e: Error) => toast(e.message, true),
  });

  // GPX Race Pacer state
  const [aidInput, setAidInput] = useState("12, 25, 38");
  const [fadePct, setFadePct] = useState("8");
  const [carbsH, setCarbsH] = useState("70");
  const [gpxName, setGpxName] = useState("");
  const [plan, setPlan] = useState<any>(null);

  const runPlan = useMutation({
    mutationFn: (gpx: string) => {
      const aid_stations_km = aidInput
        .split(/[,\s]+/)
        .map((s) => Number(s.trim()))
        .filter((n) => Number.isFinite(n) && n > 0);
      return api("/insights/trail/race-plan", {
        method: "POST",
        body: {
          gpx,
          aid_stations_km: aid_stations_km.length ? aid_stations_km : null,
          fade_pct: Number(fadePct) || 8,
          carbs_g_per_h: Number(carbsH) || 70,
        },
      });
    },
    onSuccess: (res) => {
      setPlan(res);
      toast("Race pace & fueling plan ready");
    },
    onError: (e: Error) => toast(e.message, true),
  });

  if (isLoading || !data) return <Skeleton h={420} />;

  const { race, fitness, recent_4w, baseline, weeks, long_runs, shoes, coaching_flags } = data;
  const [phaseTone, phaseText] = PHASE_LABEL[race.phase] ?? ["", race.phase];
  const [acwrTone, acwrText] = ACWR_BADGE[fitness.acwr_status] ?? ["", "–"];

  const startEdit = () => {
    setForm({
      name: race.name ?? "50k Trail Race",
      date: race.date ?? "",
      distance_km: race.distance_km ?? 50,
      elevation_gain_m: race.elevation_gain_m ?? 2000,
      weekly_km_target: race.weekly_km_target ?? 60,
      weekly_vert_target: race.weekly_vert_target ?? 1800,
      target_carbs_g_per_h: race.target_carbs_g_per_h ?? 70,
    });
    setEditing(true);
  };

  return (
    <div className="stack gap16">
      <Card
        title={race.name || "50k Trail Race"}
        icon={IconTarget}
        hint={race.date ? `Race date ${race.date} · ${race.distance_km} km · ${int(race.elevation_gain_m)} m D+ · ${race.effort_km} e-km (${race.vert_per_km} m/km)` : "Set your 50k race date and elevation target to track phase & readiness"}
        actions={
          <div className="row" style={{ gap: 8 }}>
            <span className={`badge ${phaseTone}`}>{phaseText}</span>
            {fitness.acwr != null && <span className={`badge ${acwrTone}`}>ACWR {num(fitness.acwr, 2)}</span>}
            <button className="sm" onClick={editing ? () => setEditing(false) : startEdit}>
              {editing ? "Cancel" : "Edit target"}
            </button>
          </div>
        }
      >
        {editing && form ? (
          <div className="stack gap12">
            <div className="fields">
              <label className="field">Race name
                <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </label>
              <label className="field">Race date
                <input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} />
              </label>
              <label className="field">Distance (km)
                <input type="number" step="1" value={form.distance_km} onChange={(e) => setForm({ ...form, distance_km: Number(e.target.value) })} />
              </label>
              <label className="field">Elevation gain D+ (m)
                <input type="number" step="50" value={form.elevation_gain_m} onChange={(e) => setForm({ ...form, elevation_gain_m: Number(e.target.value) })} />
              </label>
              <label className="field">Weekly km target
                <input type="number" step="5" value={form.weekly_km_target} onChange={(e) => setForm({ ...form, weekly_km_target: Number(e.target.value) })} />
              </label>
              <label className="field">Weekly vertical target (m)
                <input type="number" step="100" value={form.weekly_vert_target} onChange={(e) => setForm({ ...form, weekly_vert_target: Number(e.target.value) })} />
              </label>
            </div>
            <div className="row">
              <button className="primary sm" disabled={saveGoal.isPending} onClick={() => saveGoal.mutate({ ...form, date: form.date || null })}>
                {saveGoal.isPending ? "Saving…" : "Save race target"}
              </button>
            </div>
          </div>
        ) : (
          <div className="stats">
            <Stat label="Countdown" value={race.days_to_race != null ? `${race.days_to_race} d` : "–"} unit={race.weeks_to_race != null ? `(${race.weeks_to_race} wk)` : "set date"} />
            <Stat label="4w avg / wk" value={num(recent_4w.avg_weekly_km, 1)} unit={`km · ${int(recent_4w.avg_weekly_elevation_m)} m`} />
            <Stat label="4w Effort-km" value={num(recent_4w.avg_weekly_effort_km, 1)} unit="e-km/wk" title="ITRA Effort-km: km + D+/100" />
            <Stat label="Vert specificity" value={num(recent_4w.vert_per_km, 0)} unit={`m/km (race ${num(race.vert_per_km, 0)})`} />
            <Stat label="ACWR" value={fitness.acwr != null ? num(fitness.acwr, 2) : "–"} unit={acwrText} title="Acute:Chronic Workload Ratio (ATL / CTL). 0.8–1.3 is optimal" />
            <Stat label="Median GAP" value={baseline.median_gap_pace || "–"} unit={baseline.median_climb_vam_mh ? `VAM ${int(baseline.median_climb_vam_mh)} m/h` : undefined} />
            <Stat label="Longest (8w)" value={num(recent_4w.max_long_run_km, 1)} unit="km" />
            <Stat label="Back-to-back" value={num(recent_4w.max_back_to_back_km, 1)} unit="km (2d)" title="Biggest consecutive 2-day running volume in the last 8 weeks" />
          </div>
        )}
      </Card>

      {coaching_flags.length > 0 && (
        <div className="stack" style={{ gap: 8 }}>
          {coaching_flags.map((f: any) => (
            <Callout key={f.code + f.message} kind={f.severity === "bad" ? "bad" : f.severity === "warn" ? "warn" : f.severity === "good" ? "good" : "info"}>
              {f.message}
            </Callout>
          ))}
        </div>
      )}

      <Card title="8-week trail build" icon={MetricIcon.climb} hint={`Weekly targets: ${race.weekly_km_target} km · ${int(race.weekly_vert_target)} m D+`} flush>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Week</th>
                <th className="r">Runs</th>
                <th className="r">km</th>
                <th className="r">D+ (m)</th>
                <th className="r">Effort-km</th>
                <th className="r">Long</th>
                <th className="r">2-day B2B</th>
                <th className="r hide-mobile">m/km</th>
              </tr>
            </thead>
            <tbody>
              {[...weeks].reverse().map((w: any) => (
                <tr key={w.week_start}>
                  <td className="num" style={{ whiteSpace: "nowrap" }}>{w.week_start}</td>
                  <td className="r">{w.runs}</td>
                  <td className="r">{num(w.distance_km, 1)}</td>
                  <td className="r">{int(w.elevation_m)}</td>
                  <td className="r"><b>{num(w.effort_km, 1)}</b></td>
                  <td className="r">{w.longest_km > 0 ? `${num(w.longest_km, 1)} km` : "–"}</td>
                  <td className="r">{w.back_to_back_km > 0 ? `${num(w.back_to_back_km, 1)} km` : "–"}</td>
                  <td className="r hide-mobile muted">{w.vert_per_km > 0 ? int(w.vert_per_km) : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid g2">
        <Card title="Long-run durability" icon={MetricIcon.hr} hint="Runs ≥ 75 min · HR drift under 5% indicates strong aerobic durability" flush>
          {long_runs.length ? (
            <div className="list">
              {long_runs.map((r: any) => {
                const dec = r.decoupling_pct;
                const tone = dec == null ? "" : dec <= 5 ? "good" : dec <= 7 ? "warn" : "bad";
                return (
                  <Link key={r.id} to={`/activities/${r.id}`} className="item">
                    <div className="main-col">
                      <span className="name small">{r.name}</span>
                      <div className="metrics">
                        <span>{r.date}</span>
                        <span>{num(r.distance_km, 1)} km</span>
                        <span>+{int(r.elevation_m)} m</span>
                        {r.gap_pace && <span>GAP {r.gap_pace}</span>}
                      </div>
                    </div>
                    <div className="side">
                      {dec != null && <span className={`badge ${tone}`}>{dec > 0 ? `+${dec}%` : `${dec}%`} drift</span>}
                      <span className="xs muted">{duration(r.moving_time_s)}</span>
                    </div>
                  </Link>
                );
              })}
            </div>
          ) : (
            <Empty title="No long runs (≥ 75 min) with tracks yet" />
          )}
        </Card>

        <Card title="GPX race pacer & fueling" icon={IconImport} hint="Upload your 50k GPX route to estimate aid-station splits & carbs from your own GAP">
          <div className="stack gap12">
            <div className="fields">
              <label className="field">Aid stations (km, comma-separated)
                <input value={aidInput} onChange={(e) => setAidInput(e.target.value)} placeholder="12, 25, 38" />
              </label>
              <label className="field">Late-race fade (%)
                <input type="number" step="1" value={fadePct} onChange={(e) => setFadePct(e.target.value)} />
              </label>
              <label className="field">Carbs target (g/h)
                <input type="number" step="5" value={carbsH} onChange={(e) => setCarbsH(e.target.value)} />
              </label>
            </div>
            <div className="row">
              <label className="btn primary sm" style={{ cursor: "pointer" }}>
                <IconImport size={15} />
                {runPlan.isPending ? "Calculating…" : gpxName ? `Loaded: ${gpxName}` : "Choose GPX file"}
                <input
                  type="file"
                  accept=".gpx,application/gpx+xml,text/xml"
                  style={{ display: "none" }}
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    setGpxName(f.name);
                    const text = await f.text();
                    runPlan.mutate(text);
                  }}
                />
              </label>
              <span className="xs muted">Baseline GAP: {baseline.median_gap_pace || "6:15/km default"}</span>
            </div>

            {plan && (
              <div className="stack gap12">
                <div className="stats">
                  <Stat label="Predicted finish" value={duration(plan.est_total_s, true)} unit={plan.est_avg_pace} />
                  <Stat label="Distance / D+" value={`${plan.distance_km} km`} unit={`+${int(plan.elevation_gain_m)} m`} />
                  <Stat label="Effort-km" value={plan.effort_km} unit={`${plan.vert_per_km} m/km`} />
                  <Stat label="Fueling" value={`${int(plan.total_carbs_g)} g`} unit={`${plan.total_fluid_l} L fluid`} />
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>Leg</th><th className="r">km</th><th className="r">+m / -m</th><th className="r">Split</th><th className="r">Cumul.</th><th className="r">Carbs</th></tr>
                    </thead>
                    <tbody>
                      {plan.legs.map((l: any) => (
                        <tr key={l.leg}>
                          <td className="num" style={{ whiteSpace: "nowrap" }}>{l.from_km}–{l.to_km}</td>
                          <td className="r">{l.distance_km}</td>
                          <td className="r" style={{ whiteSpace: "nowrap" }}>+{int(l.gain_m)} / -{int(l.loss_m)}</td>
                          <td className="r">{duration(l.est_duration_s, true)}</td>
                          <td className="r"><b>{duration(l.est_cumulative_s, true)}</b></td>
                          <td className="r">{int(l.carbs_g)} g</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </Card>
      </div>

      {shoes.length > 0 && (
        <Card title="Trail shoes" hint="Monitor midsole wear before your 50k" flush>
          <div className="list">
            {shoes.map((s: any) => (
              <div key={s.label} className="item" style={{ cursor: "default" }}>
                <div className="main-col">
                  <b className="small">{s.label}</b>
                  <span className="meta">{s.runs} runs · {s.distance_km} km{s.service_km ? ` / ${s.service_km} km target` : ""}</span>
                </div>
                <div className="side">
                  {s.service_due || (!s.service_km && s.distance_km >= 650) ? <span className="badge warn">Check wear</span> : <span className="badge good">OK</span>}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title="AI Trail Coach (MCP)" icon={IconApi} hint="Connect Claude, ChatGPT, or Cursor to /mcp for personalized 50k coaching">
        <div className="stack" style={{ gap: 8 }}>
          <p className="small secondary" style={{ margin: 0 }}>
            Your RoutePass MCP server exposes dedicated trail-running coaching tools and a 1-click prompt (<span className="mono">trail_coach_review</span>):
          </p>
          <div className="chips">
            <span className="badge info mono">get_trail_training_brief</span>
            <span className="badge info mono">analyze_trail_activity</span>
            <span className="badge info mono">plan_trail_race_gpx</span>
            <span className="badge info mono">set_trail_race_goal</span>
          </div>
          <p className="xs muted" style={{ margin: 0 }}>
            Try asking your AI assistant: <em>“Run my RoutePass trail_coach_review and suggest next week's key sessions for my 50k.”</em>
          </p>
        </div>
      </Card>
    </div>
  );
}
