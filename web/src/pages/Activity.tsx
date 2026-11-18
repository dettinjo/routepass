import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useCallback, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { HBars, LineChart } from "../components/charts";
import { IconDownload, IconExternal, IconLeft, IconLock, IconRefresh, IconRight } from "../components/icons";
import { TrackMap } from "../components/maps";
import { Card, Empty, ProviderBadges, Skeleton, SportDot, Stat, StatusBadge, useToast } from "../components/ui";
import { api, downloadUrl } from "../lib/api";
import { familyColor } from "../lib/colors";
import { activityDate, dateTime, duration, int, km, num, speed } from "../lib/format";
import type { ActivityDetail, ActivityRow, TrackPoint } from "../lib/types";
import { ActivityList } from "./Dashboard";

const ZONE_COLORS = ["var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)", "var(--seq-6)", "var(--series-8)"];
const DIST_LABEL: Record<string, string> = {
  "400": "400 m", "1000": "1 km", "1609": "1 mile", "5000": "5 km", "10000": "10 km", "20000": "20 km", "21097": "Half marathon",
  "40000": "40 km", "42195": "Marathon", "50000": "50 km", "100000": "100 km", "160934": "100 miles",
};
const durLabel = (s: number) => (s < 60 ? `${s} s` : s < 3600 ? `${s / 60} min` : `${s / 3600} h`);
const DIRS = [
  { key: "komoot_to_strava", label: "Komoot → Strava", target: "Strava" },
  { key: "strava_to_komoot", label: "Strava → Komoot", target: "Komoot" },
];

function useAction() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: ({ path, body, method = "POST" }: { path: string; body?: unknown; method?: string }) => api(path, { method, body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["activity"] });
      qc.invalidateQueries({ queryKey: ["activities"] });
    },
    onError: (e: Error) => toast(e.message, true),
  });
}

function StreamCharts({ points, family, onHover }: { points: TrackPoint[]; family: string; onHover: (i: number | null) => void }) {
  const useDistance = points.some((p) => p.d != null && p.d > 0);
  const x = useMemo(() => points.map((p) => (useDistance ? (p.d ?? 0) / 1000 : p.t / 60)), [points, useDistance]);
  const xFormat = (v: number) => (useDistance ? `${v.toFixed(1)} km` : `${v.toFixed(0)} min`);
  const pace = family === "run" || family === "walk";
  const defs = [
    { key: "ele", label: "Elevation", unit: "m", color: "var(--series-6)", get: (p: TrackPoint) => p.ele, fmt: (v: number) => `${v.toFixed(0)} m`, fill: true },
    pace
      ? { key: "v", label: "Pace", unit: "/km", color: "var(--series-1)", get: (p: TrackPoint) => (p.v && p.v > 0.5 ? 1000 / p.v / 60 : null), fmt: (v: number) => `${Math.floor(v)}:${String(Math.round((v % 1) * 60)).padStart(2, "0")}` }
      : { key: "v", label: "Speed", unit: "km/h", color: "var(--series-1)", get: (p: TrackPoint) => (p.v != null ? p.v * 3.6 : null), fmt: (v: number) => `${v.toFixed(1)} km/h` },
    { key: "hr", label: "Heart rate", unit: "bpm", color: "var(--series-8)", get: (p: TrackPoint) => p.hr, fmt: (v: number) => `${v.toFixed(0)} bpm` },
    { key: "pw", label: "Power", unit: "W", color: "var(--series-7)", get: (p: TrackPoint) => p.pw, fmt: (v: number) => `${v.toFixed(0)} W` },
    { key: "cad", label: "Cadence", unit: "rpm", color: "var(--series-4)", get: (p: TrackPoint) => p.cad, fmt: (v: number) => `${v.toFixed(0)}` },
    { key: "temp", label: "Temperature", unit: "°C", color: "var(--series-2)", get: (p: TrackPoint) => p.temp, fmt: (v: number) => `${v.toFixed(1)} °C` },
  ];
  const charts = defs
    .map((d) => ({ ...d, values: points.map(d.get) }))
    .filter((d) => d.values.some((v) => v != null && v !== 0));
  return (
    <div className="stack" style={{ gap: 4 }}>
      {charts.map((c) => (
        <div key={c.key}>
          <div className="small secondary" style={{ fontWeight: 500 }}>{c.label}</div>
          <LineChart
            x={x}
            series={[{ label: c.label, color: c.color, values: c.values, fill: c.fill, width: 1.5 }]}
            height={c.key === "ele" ? 150 : 110}
            xFormat={xFormat}
            yFormat={c.fmt}
            syncKey="activity"
            onCursor={onHover}
          />
        </div>
      ))}
    </div>
  );
}

export default function ActivityPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const action = useAction();
  const [hover, setHover] = useState<number | null>(null);
  const [mergeId, setMergeId] = useState("");
  const { data: a, isLoading, error } = useQuery<ActivityDetail>({ queryKey: ["activity", id], queryFn: () => api(`/activities/${id}`) });
  const { data: track } = useQuery<{ points: TrackPoint[]; channels: string[]; provider: string | null }>({
    queryKey: ["activity", id, "track"], queryFn: () => api(`/activities/${id}/track`),
  });
  const { data: similar } = useQuery<ActivityRow[]>({ queryKey: ["activity", id, "similar"], queryFn: () => api(`/activities/${id}/similar`) });

  const latlng = useMemo(
    () => (track?.points || []).filter((p) => p.lat != null && p.lon != null).map((p) => [p.lat!, p.lon!] as [number, number]),
    [track],
  );
  const climbSegs = useMemo(() => {
    if (!track || !a?.analysis?.climbs) return [];
    return a.analysis.climbs.slice(0, 10).map((c) =>
      track.points.filter((p) => p.d != null && p.d >= c.start_m && p.d <= c.end_m && p.lat != null).map((p) => [p.lat!, p.lon!] as [number, number]),
    );
  }, [track, a]);
  const highlight = useMemo(() => {
    if (hover == null || !track) return null;
    const p = track.points[hover];
    return p?.lat != null && p?.lon != null ? ([p.lat, p.lon] as [number, number]) : null;
  }, [hover, track]);
  const onHover = useCallback((i: number | null) => setHover(i), []);

  if (isLoading) return <Skeleton h={500} />;
  if (error || !a) return <Empty title="Activity not found"><Link to="/activities">Back to activities</Link></Empty>;
  const an = a.analysis;
  const live = a.sources.filter((s) => !s.deleted);

  return (
    <>
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <div className="row small muted" style={{ marginBottom: 6 }}>
            <Link to="/activities">Activities</Link><span>/</span><span>{a.sport_label}</span>
          </div>
          <h1 className="row" style={{ gap: 10 }}><SportDot family={a.family} />{a.name}{a.sync_locked && <IconLock width={16} className="muted" />}</h1>
          <div className="sub">{activityDate(a)}{a.trainer && " · indoor"}{a.commute && " · commute"}{a.device && ` · ${a.device}`}</div>
        </div>
        <div className="row">
          <button className="sm" disabled={!a.prev_id} onClick={() => nav(`/activities/${a.prev_id}`)} title="Previous (older)"><IconLeft /></button>
          <button className="sm" disabled={!a.next_id} onClick={() => nav(`/activities/${a.next_id}`)} title="Next (newer)"><IconRight /></button>
          {a.has_track && <a className="btn" href={downloadUrl(`/activities/${a.id}/gpx`)}><IconDownload width={15} />GPX</a>}
        </div>
      </div>

      <div className="stack gap16">
        <Card>
          <div className="stats">
            <Stat label="Distance" value={km(a.distance_m, 2)} unit="km" />
            <Stat label="Moving time" value={duration(a.moving_time_s, true)} />
            <Stat label="Elapsed" value={duration(a.elapsed_time_s, true)} />
            <Stat label="Elevation gain" value={int(a.elevation_gain_m)} unit="m" />
            {a.elevation_loss_m != null && <Stat label="Elevation loss" value={int(a.elevation_loss_m)} unit="m" />}
            {a.elevation_max_m != null && <Stat label="Highest point" value={int(a.elevation_max_m)} unit="m" />}
            <Stat label={a.family === "run" || a.family === "walk" ? "Avg pace" : "Avg speed"} value={speed(a.avg_speed_ms, a.family)} />
            {a.max_speed_ms != null && <Stat label="Max speed" value={num(a.max_speed_ms * 3.6)} unit="km/h" />}
            {a.avg_hr != null && <Stat label="Avg HR" value={int(a.avg_hr)} unit="bpm" />}
            {a.max_hr != null && <Stat label="Max HR" value={int(a.max_hr)} unit="bpm" />}
            {a.avg_power != null && <Stat label="Avg power" value={int(a.avg_power)} unit="W" />}
            {a.normalized_power != null && <Stat label="Norm. power" value={int(a.normalized_power)} unit="W" />}
            {a.avg_cadence != null && <Stat label="Cadence" value={int(a.avg_cadence)} />}
            {a.work_kj != null && <Stat label="Work" value={int(a.work_kj)} unit="kJ" />}
            {a.avg_temp != null && <Stat label="Temperature" value={num(a.avg_temp)} unit="°C" />}
            {a.load != null && <Stat label="Load" value={int(a.load)} title={`Method: ${a.load_method}`} unit={a.load_method === "estimate" ? "est." : undefined} />}
            {a.intensity != null && <Stat label="Intensity" value={num(a.intensity, 2)} />}
            {an?.decoupling && <Stat label="Decoupling" value={`${an.decoupling.pct > 0 ? "+" : ""}${an.decoupling.pct}%`} title={`${an.decoupling.metric}:HR drift, first vs second half. <5% = aerobically steady`} />}
          </div>
        </Card>

        <div className="grid g2">
          <Card title="Route" hint={climbSegs.length ? "Climbs highlighted" : undefined} flush={false}>
            <TrackMap points={latlng} highlight={highlight} climbs={climbSegs} />
          </Card>
          <Card title="Streams" hint={track?.provider ? `Recorded data from ${track.provider}` : undefined}>
            {track?.points.length ? <StreamCharts points={track.points} family={a.family} onHover={onHover} /> : (
              <Empty title={a.has_track ? "Loading…" : "No recording downloaded yet"}>
                <button className="sm mt8" onClick={() => action.mutate({ path: `/activities/${a.id}/refetch-track` }, { onSuccess: () => toast("Track download queued") })}>
                  <IconRefresh />Download now
                </button>
              </Empty>
            )}
          </Card>
        </div>

        {an && (
          <div className="grid g3">
            {an.hr_zones && (
              <Card title="Heart-rate zones" hint={`Based on ${an.hr_zones.basis === "profile" ? "your max HR" : "this activity's max HR"}`}>
                <HBars
                  format={(v) => duration(v)}
                  rows={an.hr_zones.seconds.map((s, i) => ({
                    label: `Z${i + 1} ${i === 0 ? `<${an.hr_zones!.bounds[0]}` : i === an.hr_zones!.bounds.length ? `>${an.hr_zones!.bounds[i - 1]}` : `${an.hr_zones!.bounds[i - 1]}–${an.hr_zones!.bounds[i]}`}`,
                    value: s, color: ZONE_COLORS[i + 1],
                  }))}
                />
              </Card>
            )}
            {an.power_zones && (
              <Card title="Power zones" hint={`FTP ${an.power_zones.ftp} W`}>
                <HBars format={(v) => duration(v)} rows={an.power_zones.seconds.map((s, i) => ({ label: `Z${i + 1}`, value: s, color: ZONE_COLORS[Math.min(i, 6)] }))} />
              </Card>
            )}
            {an.best_times && Object.keys(an.best_times).length > 0 && (
              <Card title="Best efforts">
                <dl className="kv">
                  {Object.entries(an.best_times).map(([d, t]) => (<Fragment key={d}><dt>{DIST_LABEL[d] ?? `${d} m`}</dt><dd>{duration(t, true)} <span className="muted small">{speed(Number(d) / t, a.family)}</span></dd></Fragment>))}
                </dl>
              </Card>
            )}
            {an.power_curve && Object.keys(an.power_curve).length > 0 && (
              <Card title="Peak power">
                <dl className="kv">
                  {Object.entries(an.power_curve).map(([s, w]) => (<Fragment key={s}><dt>{durLabel(Number(s))}</dt><dd>{int(w)} W</dd></Fragment>))}
                </dl>
              </Card>
            )}
          </div>
        )}

        {an?.splits && an.splits.length > 1 && (
          <Card title="Splits" hint={`Every ${km(an.split_m ?? 1000, 0)} km`} flush>
            <div className="table-wrap" style={{ maxHeight: 420 }}>
              <table>
                <thead><tr><th>#</th><th className="r">Distance</th><th className="r">Time</th><th className="r">{a.family === "run" || a.family === "walk" ? "Pace" : "Speed"}</th>{an.splits.some((s) => s.hr != null) && <th className="r">HR</th>}{an.splits.some((s) => s.power != null) && <th className="r">Power</th>}<th className="r">Gain</th><th className="r">Loss</th><th style={{ width: "30%" }} /></tr></thead>
                <tbody>
                  {(() => {
                    const maxV = Math.max(...an.splits!.map((s) => s.speed_ms || 0));
                    const hasHr = an.splits!.some((s) => s.hr != null);
                    const hasPw = an.splits!.some((s) => s.power != null);
                    return an.splits!.map((s) => (
                      <tr key={s.index}>
                        <td>{s.index}</td><td className="r">{km(s.distance_m, 2)}</td><td className="r">{duration(s.duration_s, true)}</td>
                        <td className="r">{speed(s.speed_ms, a.family)}</td>{hasHr && <td className="r">{int(s.hr)}</td>}{hasPw && <td className="r">{int(s.power)}</td>}
                        <td className="r">{int(s.gain_m)}</td><td className="r">{int(s.loss_m)}</td>
                        <td><div className="bar-track"><div className="bar-fill" style={{ width: `${((s.speed_ms || 0) / maxV) * 100}%`, background: familyColor(a.family) }} /></div></td>
                      </tr>
                    ));
                  })()}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {an?.climbs && an.climbs.length > 0 && (
          <Card title="Climbs" hint="Continuous ascents of at least 30 m" flush>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Start</th><th className="r">Length</th><th className="r">Gain</th><th className="r">Avg grade</th><th className="r">Time</th><th className="r">VAM</th><th className="r">Top</th></tr></thead>
                <tbody>
                  {an.climbs.map((c, i) => (
                    <tr key={i}><td>km {km(c.start_m)}</td><td className="r">{km(c.length_m, 2)} km</td><td className="r">{int(c.gain_m)} m</td><td className="r">{num(c.grade_pct)}%</td><td className="r">{duration(c.duration_s, true)}</td><td className="r">{int(c.vam)} m/h</td><td className="r">{int(c.top_m)} m</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        <div className="grid g2">
          <Card title="Platforms" hint="One activity, its records on each platform">
            <div className="stack">
              {a.sources.map((s) => (
                <div key={s.id} className="row between" style={{ opacity: s.deleted ? 0.5 : 1 }}>
                  <div className="row" style={{ gap: 10 }}>
                    <span className={`prov ${s.provider}`}>{s.provider === "strava" ? "S" : "K"}</span>
                    <div>
                      <a href={s.url} target="_blank" rel="noreferrer" className="row" style={{ gap: 4 }}>{s.name || s.external_id}<IconExternal width={12} /></a>
                      <div className="small muted">
                        {s.created_by_sync ? "Copy created by RoutePass" : "Original recording"}
                        {s.deleted && " · deleted on platform"}{s.match_locked && " · manually linked"}{s.visibility && ` · ${s.visibility}`}
                      </div>
                    </div>
                  </div>
                  {live.length > 1 && !s.deleted && (
                    <button className="sm ghost" title="This record is a different activity — split it off"
                      onClick={() => confirm("Split this record into its own activity?") && action.mutate({ path: `/activities/${a.id}/unlink`, body: { source_id: s.id } })}>
                      Not the same
                    </button>
                  )}
                </div>
              ))}
              <div className="section-label mt8">Sync</div>
              {DIRS.map((d) => {
                const blocker = a.sync_status[d.key];
                return (
                  <div key={d.key} className="row between">
                    <span>{d.label}</span>
                    {blocker ? <span className="small muted">{blocker}</span> : (
                      <button className="sm" disabled={action.isPending}
                        onClick={() => action.mutate({ path: `/activities/${a.id}/sync`, body: { direction: d.key } }, {
                          onSuccess: (r: any) => toast(r.job.status === "done" ? `Copied to ${d.target}` : `Job ${r.job.status}: ${r.job.reason || r.job.error || ""}`, r.job.status === "failed"),
                        })}>
                        Copy to {d.target} now
                      </button>
                    )}
                  </div>
                );
              })}
              <div className="row between">
                <span>Lock from automatic sync</span>
                <button className="sm" onClick={() => action.mutate({ path: `/activities/${a.id}`, method: "PATCH", body: { sync_locked: !a.sync_locked } })}>
                  {a.sync_locked ? "Unlock" : "Lock"}
                </button>
              </div>
              {a.sync_jobs.length > 0 && (
                <>
                  <div className="section-label mt8">History</div>
                  {a.sync_jobs.map((j) => (
                    <div key={j.id} className="small row between">
                      <span className="row"><StatusBadge status={j.status} />{j.direction.replace("_to_", " → ")}</span>
                      <span className="muted" title={j.error || ""}>{j.reason}{j.target_url && <> · <a href={j.target_url} target="_blank" rel="noreferrer">open</a></>} · {dateTime(j.updated_at)}</span>
                    </div>
                  ))}
                </>
              )}
              <div className="section-label mt8">Merge a missed duplicate</div>
              <div className="row">
                <input placeholder="Other activity id" value={mergeId} onChange={(e) => setMergeId(e.target.value)} style={{ width: 160 }} />
                <button className="sm" disabled={!mergeId} onClick={() => action.mutate({ path: `/activities/${a.id}/merge`, body: { other_id: Number(mergeId) } }, { onSuccess: () => { setMergeId(""); toast("Merged"); } })}>Merge into this</button>
              </div>
            </div>
          </Card>
          <Card title="Same route" hint="Same sport, similar distance, starting nearby" flush>
            {similar?.length ? <ActivityList items={similar} compact /> : <div className="empty">No repeats found</div>}
          </Card>
        </div>
        <p className="small muted">Activity #{a.id} · <ProviderBadges providers={a.providers} copies={a.copies} all /></p>
      </div>
    </>
  );
}
