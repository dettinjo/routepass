import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { HBars } from "../components/charts";
import {
  BrandIcon, IconDownload, IconExternal, IconHistory, IconLeft, IconLock, IconMap, IconRefresh, IconRight,
  IconSync, IconTarget, IconTrophy, IconUnlock, MetricIcon, providerName,
} from "../components/icons";
import { TrackMap } from "../components/maps";
import { ActivityList } from "../components/shared";
import { StreamStack } from "../components/streams";
import { Callout, Card, Empty, Skeleton, SportBadge, Stat, StatusBadge, Tabs, useToast } from "../components/ui";
import { api, downloadUrl } from "../lib/api";
import { familyColor } from "../lib/colors";
import { activityDate, dateTime, duration, int, km, num, speed } from "../lib/format";
import type { ActivityDetail, ActivityRow, TrackPoint } from "../lib/types";

const ZONE_COLORS = ["var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)", "var(--seq-6)", "var(--series-8)"];
const DIST_LABEL: Record<string, string> = {
  "400": "400 m", "1000": "1 km", "1609": "1 mile", "5000": "5 km", "10000": "10 km", "20000": "20 km", "21097": "Half marathon",
  "40000": "40 km", "42195": "Marathon", "50000": "50 km", "100000": "100 km", "160934": "100 miles",
};
const durLabel = (s: number) => (s < 60 ? `${s} s` : s < 3600 ? `${s / 60} min` : `${s / 3600} h`);
const DIRS = [
  { key: "komoot_to_strava", from: "komoot", to: "strava" },
  { key: "strava_to_komoot", from: "strava", to: "komoot" },
];
type Tab = "overview" | "analysis" | "sync";

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

function Analysis({ a, onSelectClimb }: { a: ActivityDetail; onSelectClimb?: (idx: number) => void }) {
  const an = a.analysis;
  const { data: similar } = useQuery<ActivityRow[]>({ queryKey: ["activity", String(a.id), "similar"], queryFn: () => api(`/activities/${a.id}/similar`) });
  if (!an) return <Empty title="No recording analysed yet" icon={IconMap}>The track is downloaded in the background.</Empty>;
  const foot = a.family === "run" || a.family === "walk";
  const hasHr = an.splits?.some((s) => s.hr != null);
  const hasPw = an.splits?.some((s) => s.power != null);
  const hasGap = foot && an.splits?.some((s) => s.gap_speed_ms != null);
  return (
    <div className="stack gap16">
      <div className="grid g2">
        {an.hr_zones && (
          <Card title="Heart-rate zones" icon={MetricIcon.hr} hint={an.hr_zones.basis === "profile" ? "From your max heart rate" : "From this activity's max HR — set yours in Settings"}>
            <HBars format={(v) => duration(v)} rows={an.hr_zones.seconds.map((s, i) => ({
              label: `Z${i + 1} ${i === 0 ? `<${an.hr_zones!.bounds[0]}` : i === an.hr_zones!.bounds.length ? `>${an.hr_zones!.bounds[i - 1]}` : `${an.hr_zones!.bounds[i - 1]}–${an.hr_zones!.bounds[i]}`}`,
              value: s, color: ZONE_COLORS[i + 1],
            }))} />
          </Card>
        )}
        {an.power_zones && (
          <Card title="Power zones" icon={MetricIcon.power} hint={`FTP ${an.power_zones.ftp} W`}>
            <HBars format={(v) => duration(v)} rows={an.power_zones.seconds.map((s, i) => ({ label: `Z${i + 1}`, value: s, color: ZONE_COLORS[Math.min(i, 6)] }))} />
          </Card>
        )}
        {an.best_times && Object.keys(an.best_times).length > 0 && (
          <Card title="Best efforts" icon={IconTrophy}>
            <div className="stack" style={{ gap: 8 }}>
              {Object.entries(an.best_times).map(([d, t]) => (
                <div key={d} className="row between nowrap small">
                  <span className="secondary">{DIST_LABEL[d] ?? `${d} m`}</span>
                  <span className="num"><b>{duration(t, true)}</b> <span className="muted">{speed(Number(d) / t, a.family)}</span></span>
                </div>
              ))}
            </div>
          </Card>
        )}
        {an.power_curve && Object.keys(an.power_curve).length > 0 && (
          <Card title="Peak power" icon={MetricIcon.power}>
            <div className="stack" style={{ gap: 8 }}>
              {Object.entries(an.power_curve).map(([s, w]) => (
                <div key={s} className="row between nowrap small"><span className="secondary">{durLabel(Number(s))}</span><b className="num">{int(w)} W</b></div>
              ))}
            </div>
          </Card>
        )}
      </div>

      {an.splits && an.splits.length > 1 && (
        <Card title="Splits" icon={MetricIcon.length} hint={`Every ${km(an.split_m ?? 1000, 0)} km`} flush>
          <div className="table-wrap" style={{ maxHeight: 440 }}>
            <table>
              <thead><tr><th>km</th><th className="r">{foot ? "Pace" : "Speed"}</th>{hasGap && <th className="r">GAP</th>}<th className="hide-mobile" style={{ width: "28%" }} /><th className="r">Time</th><th className="r">+m</th>{hasHr && <th className="r">HR</th>}{hasPw && <th className="r hide-mobile">W</th>}</tr></thead>
              <tbody>
                {(() => {
                  const maxV = Math.max(...an.splits!.map((s) => s.speed_ms || 0));
                  let cum = 0;
                  return an.splits!.map((s) => {
                    cum += s.distance_m;
                    return (
                      <tr key={s.index}>
                        <td className="num">{km(cum, cum < 10000 ? 1 : 0)}</td>
                        <td className="r" style={{ whiteSpace: "nowrap" }}>{speed(s.speed_ms, a.family)}</td>
                        {hasGap && <td className="r muted" style={{ whiteSpace: "nowrap" }}>{s.gap_speed_ms ? speed(s.gap_speed_ms, a.family) : "–"}</td>}
                        <td className="hide-mobile"><div className="bar-track"><div className="bar-fill" style={{ width: `${((s.speed_ms || 0) / maxV) * 100}%`, background: familyColor(a.family) }} /></div></td>
                        <td className="r">{duration(s.duration_s, true)}</td>
                        <td className="r">{int(s.gain_m)}</td>
                        {hasHr && <td className="r">{int(s.hr)}</td>}
                        {hasPw && <td className="r hide-mobile">{int(s.power)}</td>}
                      </tr>
                    );
                  });
                })()}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {an.climbs && an.climbs.length > 0 && (
        <Card title="Climbs" icon={MetricIcon.climb} hint="Tap any climb to zoom on the Topo map" flush>
          <div className="list">
            {an.climbs.map((c, i) => (
              <div key={i} className="item" onClick={() => onSelectClimb?.(i)} style={{ cursor: onSelectClimb ? "pointer" : "default" }}>
                <span className="sport-badge" style={{ width: 36, height: 36, background: "var(--warn-soft)", color: "var(--warn)" }}><MetricIcon.climb size={18} /></span>
                <div className="main-col">
                  <b className="small">{int(c.gain_m)} m up · {num(c.grade_pct)} %</b>
                  <div className="metrics">
                    <span><MetricIcon.distance size={13} />km {km(c.start_m)} – {km(c.end_m)}</span>
                    <span><MetricIcon.time size={13} />{duration(c.duration_s, true)}</span>
                    <span><MetricIcon.speed size={13} />{int(c.vam)} m/h</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title="Same route" icon={IconTarget} hint="Same sport, similar distance, starting nearby" flush>
        {similar?.length ? <ActivityList items={similar} /> : <div className="empty">No repeats found</div>}
      </Card>
    </div>
  );
}

function SyncTab({ a }: { a: ActivityDetail }) {
  const action = useAction();
  const toast = useToast();
  const [mergeId, setMergeId] = useState("");
  const live = a.sources.filter((s) => !s.deleted);
  return (
    <div className="stack gap16">
      <Card title="Platforms" icon={IconSync} hint="This activity and its record on each platform" flush>
        <div className="list">
          {["strava", "komoot"].map((p) => {
            const s = a.sources.find((x) => x.provider === p && !x.deleted);
            const dir = DIRS.find((d) => d.to === p)!;
            const blocker = a.sync_status[dir.key];
            return (
              <div key={p} className="item" style={{ cursor: "default" }}>
                <span className="prov" style={{ width: 40, height: 40, borderRadius: 12 }}><BrandIcon provider={p} size={22} /></span>
                <div className="main-col">
                  {s ? (
                    <>
                      <a href={s.url} target="_blank" rel="noreferrer" className="name ellipsis row nowrap" style={{ gap: 4 }}>{s.name || s.external_id}<IconExternal size={14} /></a>
                      <span className="meta">{s.created_by_sync ? "Copy created by RoutePass" : "Original recording"}{s.match_locked ? " · linked by hand" : ""}{s.visibility ? ` · ${s.visibility}` : ""}</span>
                    </>
                  ) : (
                    <>
                      <span className="name">Not on {providerName(p)}</span>
                      <span className="meta">{blocker ?? `Can be copied from ${providerName(dir.from)}`}</span>
                    </>
                  )}
                </div>
                {s && live.length > 1 && (
                  <button className="sm ghost" onClick={() => confirm("Split this record into its own activity?") && action.mutate({ path: `/activities/${a.id}/unlink`, body: { source_id: s.id } })}>
                    Not the same
                  </button>
                )}
                {!s && !blocker && (
                  <button className="sm primary" disabled={action.isPending}
                    onClick={() => action.mutate({ path: `/activities/${a.id}/sync`, body: { direction: dir.key } }, {
                      onSuccess: (r: any) => toast(r.job.status === "done" ? `Copied to ${providerName(p)}` : `${r.job.status}: ${r.job.reason || r.job.error || ""}`, r.job.status === "failed"),
                    })}>
                    Copy now
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      <Card title={a.sync_locked ? "Locked from automatic sync" : "Automatic sync"} icon={a.sync_locked ? IconLock : IconUnlock}
        actions={<button className="sm" onClick={() => action.mutate({ path: `/activities/${a.id}`, method: "PATCH", body: { sync_locked: !a.sync_locked } })}>{a.sync_locked ? "Unlock" : "Lock"}</button>}>
        <p className="small secondary">{a.sync_locked ? "RoutePass will never copy this activity automatically." : "Rules decide whether this activity is copied. Lock it to keep it where it is."}</p>
      </Card>

      {a.sync_jobs.length > 0 && (
        <Card title="Sync history" icon={IconHistory} flush>
          <div className="list">
            {a.sync_jobs.map((j) => (
              <div key={j.id} className="item" style={{ cursor: "default" }}>
                <span className="row nowrap" style={{ gap: 4 }}><BrandIcon provider={j.source_provider} size={16} /><IconRight size={14} /><BrandIcon provider={j.target_provider} size={16} /></span>
                <div className="main-col">
                  <span className="small">{j.reason}</span>
                  <span className="meta">{dateTime(j.updated_at)}{j.error ? ` · ${j.error.slice(0, 120)}` : ""}</span>
                </div>
                <div className="side"><StatusBadge status={j.status} />{j.target_url && <a href={j.target_url} target="_blank" rel="noreferrer" className="xs">open</a>}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title="Missed duplicate?" icon={IconTarget} hint="If another activity is the same recording, merge it into this one">
        <div className="row nowrap">
          <input placeholder="Other activity id" inputMode="numeric" value={mergeId} onChange={(e) => setMergeId(e.target.value)} />
          <button disabled={!mergeId} onClick={() => action.mutate({ path: `/activities/${a.id}/merge`, body: { other_id: Number(mergeId) } }, { onSuccess: () => { setMergeId(""); toast("Merged"); } })}>Merge</button>
        </div>
      </Card>
    </div>
  );
}

export default function ActivityPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const action = useAction();
  const [tab, setTab] = useState<Tab>("overview");
  const [hover, setHover] = useState<number | null>(null);
  const [focusClimbIdx, setFocusClimbIdx] = useState<number | null>(null);
  const { data: a, isLoading, error } = useQuery<ActivityDetail>({ queryKey: ["activity", id], queryFn: () => api(`/activities/${id}`) });
  const { data: track } = useQuery<{ points: TrackPoint[]; channels: string[]; provider: string | null }>({
    queryKey: ["activity", id, "track"], queryFn: () => api(`/activities/${id}/track`),
  });

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
  const focusClimb = focusClimbIdx != null ? (climbSegs[focusClimbIdx] ?? null) : null;
  const highlight = useMemo(() => {
    if (hover == null || !track) return null;
    const p = track.points[hover];
    return p?.lat != null && p?.lon != null ? ([p.lat, p.lon] as [number, number]) : null;
  }, [hover, track]);
  const onHover = useCallback((i: number | null) => setHover(i), []);
  const onSelectClimb = useCallback((idx: number) => {
    setFocusClimbIdx(idx);
    setTab("overview");
  }, []);

  if (isLoading) return <Skeleton h={500} />;
  if (error || !a) return <Empty title="Activity not found"><Link to="/activities">Back to activities</Link></Empty>;
  const an = a.analysis;
  const foot = a.family === "run" || a.family === "walk";
  const effortKm = a.distance_m ? (a.distance_m / 1000 + (a.elevation_gain_m ?? 0) / 100) : null;
  const gapSpeed = an?.summary?.gap_speed_ms ?? null;

  return (
    <>
      <div className="row between nowrap" style={{ marginBottom: 10 }}>
        <button className="ghost sm" onClick={() => nav(-1)}><IconLeft size={16} />Back</button>
        <div className="row nowrap">
          <button className="sm icon" disabled={!a.prev_id} onClick={() => nav(`/activities/${a.prev_id}`)} aria-label="Older activity"><IconLeft size={16} /></button>
          <button className="sm icon" disabled={!a.next_id} onClick={() => nav(`/activities/${a.next_id}`)} aria-label="Newer activity"><IconRight size={16} /></button>
          {a.has_track && <a className="btn sm" href={downloadUrl(`/activities/${a.id}/gpx`)} aria-label="Download GPX"><IconDownload size={16} /><span className="hide-mobile">GPX</span></a>}
        </div>
      </div>

      <div className="row nowrap" style={{ gap: 12, marginBottom: 14, alignItems: "flex-start" }}>
        <SportBadge sport={a.sport} family={a.family} size={48} />
        <div className="grow">
          <h1 className="clamp2" style={{ fontSize: 21, lineHeight: 1.25 }} title={a.name}>{a.name}{a.sync_locked && <IconLock size={16} className="muted" style={{ marginLeft: 6 }} />}</h1>
          <div className="small muted" style={{ marginTop: 3 }}>{a.sport_label} · {activityDate(a)}{a.trainer ? " · indoor" : ""}{a.commute ? " · commute" : ""}{a.gear ? ` · ${a.gear}` : ""}{a.device ? ` · ${a.device}` : ""}</div>
        </div>
      </div>

      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { value: "overview", label: "Overview" },
        { value: "analysis", label: "Analysis" },
        { value: "sync", label: <span className="row nowrap" style={{ gap: 6 }}>Sync<BrandIcon provider="strava" size={13} mono={!a.providers.includes("strava")} /><BrandIcon provider="komoot" size={13} mono={!a.providers.includes("komoot")} /></span> },
      ]} />

      {tab === "overview" && (
        <div className="stack gap16">
          <Card>
            <div className="stats">
              <Stat icon="distance" label="Distance" value={km(a.distance_m, 2)} unit="km" />
              <Stat icon="time" label="Moving time" value={duration(a.moving_time_s, true)} />
              <Stat icon="elevation" label="Climbing" value={int(a.elevation_gain_m)} unit="m" />
              <Stat icon="speed" label={foot ? "Avg pace" : "Avg speed"} value={speed(a.avg_speed_ms, a.family)} />
              {foot && gapSpeed != null && <Stat icon="climb" label="GAP" value={speed(gapSpeed, a.family)} title="Grade-Adjusted Pace (Minetti gradient cost)" />}
              {foot && effortKm != null && (a.elevation_gain_m ?? 0) >= 100 && <Stat icon="climb" label="Effort-km" value={num(effortKm, 1)} unit="e-km" title="ITRA Effort-km: distance (km) + elevation gain (m) / 100" />}
              {a.avg_hr != null && <Stat icon="hr" label="Avg heart rate" value={int(a.avg_hr)} unit={a.max_hr ? `bpm · max ${int(a.max_hr)}` : "bpm"} />}
              {a.avg_power != null && <Stat icon="power" label="Avg power" value={int(a.avg_power)} unit={a.normalized_power ? `W · NP ${int(a.normalized_power)}` : "W"} />}
              {a.load != null && <Stat icon="load" label="Training load" value={int(a.load)} unit={a.load_method === "estimate" ? "est." : undefined} title={`Method: ${a.load_method}`} />}
              <Stat icon="elapsed" label="Elapsed" value={duration(a.elapsed_time_s, true)} />
              {a.elevation_max_m != null && <Stat icon="climb" label="Highest point" value={int(a.elevation_max_m)} unit="m" />}
              {a.max_speed_ms != null && <Stat icon="speed" label="Max speed" value={num(a.max_speed_ms * 3.6)} unit="km/h" />}
              {a.avg_cadence != null && <Stat icon="count" label="Cadence" value={int(a.avg_cadence)} />}
              {a.avg_temp != null && <Stat icon="temp" label="Temperature" value={num(a.avg_temp)} unit="°C" />}
              {a.work_kj != null && <Stat icon="power" label="Work" value={int(a.work_kj)} unit="kJ" />}
              {a.tiles && a.tiles.tiles_visited > 0 && <Stat icon="days" label="Explorer tiles" value={int(a.tiles.tiles_visited)} unit={a.tiles.new_tiles ? `· ${int(a.tiles.new_tiles)} new` : undefined} title="Zoom-14 map squares this activity passed through, and how many were visited for the first time" />}
              {an?.decoupling && <Stat icon="hr" label="HR drift" value={`${an.decoupling.pct > 0 ? "+" : ""}${an.decoupling.pct}%`} title="Aerobic decoupling, first vs second half. Under 5% = steady" />}
            </div>
          </Card>
          {a.load_method === "estimate" && <Callout>Training load is estimated from duration. Add your max heart rate or FTP in <Link to="/settings">Settings</Link> for real values.</Callout>}
          <div className="grid g2">
            <Card title="Route" icon={IconMap} hint={climbSegs.length ? "Climbs in orange" : undefined}>
              <TrackMap points={latlng} highlight={highlight} climbs={climbSegs} focusClimb={focusClimb} />
            </Card>
            <Card title="Streams" icon={MetricIcon.speed} hint={track?.provider ? `Recorded data from ${providerName(track.provider)}` : undefined}>
              {track?.points.length ? <StreamStack points={track.points} family={a.family} onHover={onHover} /> : (
                <Empty title={a.has_track ? "Loading…" : "No recording downloaded yet"} icon={IconRefresh}>
                  <button className="sm" onClick={() => action.mutate({ path: `/activities/${a.id}/refetch-track` }, { onSuccess: () => toast("Download queued") })}>
                    <IconRefresh size={16} />Download now
                  </button>
                </Empty>
              )}
            </Card>
          </div>
        </div>
      )}
      {tab === "analysis" && <Analysis a={a} onSelectClimb={onSelectClimb} />}
      {tab === "sync" && <SyncTab a={a} />}
    </>
  );
}
