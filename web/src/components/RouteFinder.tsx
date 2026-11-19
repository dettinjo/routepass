import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { duration, int, num } from "../lib/format";
import { useDebouncedCallback, usePrefs, useSavePrefs } from "../lib/hooks";
import { decodePolyline } from "../lib/polyline";
import { RouteThumb } from "./charts";
import {
  BrandIcon, ICON, IconCheck, IconKeySession, IconDownload, IconExternal, IconHistory, IconLocate, IconMap, IconPlaces, IconRight,
  IconSearch, IconTrash, MetricIcon, PlanSportIcon,
} from "./icons";
import { RoutePreviewMap } from "./maps";
import { Callout, Empty, Menu, Modal, SegSelect, Skeleton, Switch, useToast } from "./ui";

export const ROUTE_SPORTS = new Set(["run", "trail_run", "bike", "ride", "cycling", "brick", "hike", "walk"]);

type Source = "history" | "komoot_saved" | "komoot_nearby";
const SOURCE: Record<Source, { label: string; short: string }> = {
  history: { label: "Your route", short: "Your routes" },
  komoot_saved: { label: "Saved in Komoot", short: "Saved in Komoot" },
  komoot_nearby: { label: "Komoot suggestion", short: "Komoot suggestions" },
};
const RADII = [5, 10, 20, 40];

interface Start { label: string; lat: number; lng: number }

function SourceIcon({ source, size = ICON.inline }: { source: string; size?: number }) {
  return source === "history" ? <IconHistory size={size} /> : <BrandIcon provider="komoot" size={size} />;
}

function fitLabel(score: number) {
  return score >= 80 ? "Great fit" : score >= 60 ? "Good fit" : "Partial fit";
}

/** "+4%" next to the distance, coloured only when it is clearly off. */
function Delta({ value, unit, tolerance }: { value?: number; unit: string; tolerance: number }) {
  if (value == null) return null;
  const off = Math.abs(value) > tolerance;
  const far = Math.abs(value) > tolerance * 2.5;
  return (
    <span className={`delta-chip ${far ? "far" : off ? "off" : "ok"}`} title={off ? "Different from the session's target" : "Close to the session's target"}>
      {value > 0 ? "+" : value < 0 ? "−" : "±"}{Math.abs(value)}{unit}
    </span>
  );
}

function Thumb({ c, size = 64 }: { c: any; size?: number }) {
  if (c.image) return <img className="route-img" src={c.image} alt="" width={size} height={size} loading="lazy" referrerPolicy="no-referrer" />;
  return <RouteThumb points={c.polyline ? decodePolyline(c.polyline) : []} size={size} color="var(--text-secondary)" />;
}

function StartPicker({ current, places, onPick, onSaveHome }: {
  current: Start | null; places: { name: string; lat: number; lng: number }[];
  onPick: (s: Start | null) => void; onSaveHome?: (s: Start) => void;
}) {
  const toast = useToast();
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const debounce = useDebouncedCallback((v: string) => setTerm(v), 600);
  const results = useQuery<{ label: string; detail: string; lat: number; lng: number }[]>({
    queryKey: ["geocode", term], queryFn: () => api("/geocode", { params: { q: term } }), enabled: term.length >= 3, staleTime: 86400_000,
  });
  const locate = () => {
    if (!navigator.geolocation) return toast("This browser cannot share its location", true);
    navigator.geolocation.getCurrentPosition(
      (p) => onPick({ label: "Your location", lat: +p.coords.latitude.toFixed(5), lng: +p.coords.longitude.toFixed(5) }),
      () => toast("Location not available — search for a place instead", true),
      { enableHighAccuracy: false, timeout: 10000 },
    );
  };
  return (
    <div className="start-picker">
      <div className="chips" style={{ flexWrap: "wrap" }}>
        {places.map((p) => (
          <button key={p.name} className={`chip ${current?.label === p.name ? "on" : ""}`} onClick={() => onPick({ label: p.name, lat: p.lat, lng: p.lng })}>
            <IconPlaces size={ICON.button} />{p.name}
          </button>
        ))}
        <button className="chip" onClick={locate}><IconLocate size={ICON.button} />My location</button>
      </div>
      <div className="search"><IconSearch size={ICON.button} />
        <input type="search" placeholder="Search a town, trailhead or address" value={q} onChange={(e) => { setQ(e.target.value); debounce(e.target.value.trim()); }} />
      </div>
      {term.length >= 3 && (
        <div className="view-list">
          {results.isFetching && <span className="small muted">Searching…</span>}
          {results.data?.map((r) => (
            <button key={`${r.lat},${r.lng}`} onClick={() => { onPick({ label: r.label, lat: r.lat, lng: r.lng }); setQ(""); setTerm(""); }}>
              <IconPlaces size={ICON.button} /><span className="stack" style={{ gap: 0, alignItems: "flex-start" }}><span>{r.label}</span><span className="xs muted ellipsis" style={{ maxWidth: 420 }}>{r.detail}</span></span>
            </button>
          ))}
          {results.data && !results.data.length && !results.isFetching && <span className="small muted">No places found.</span>}
          <span className="xs muted">Search by OpenStreetMap</span>
        </div>
      )}
      {current && onSaveHome && !places.some((p) => p.name === current.label) && (
        <button className="sm ghost" onClick={() => onSaveHome(current)}><IconPlaces size={ICON.button} />Save “{current.label}” as Home</button>
      )}
    </div>
  );
}

/** Find and attach a route for one training session. Read-only: nothing is created on Komoot. */
export function RouteFinder({ session, planId, onClose }: { session: any; planId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: prefs } = usePrefs();
  const savePrefs = useSavePrefs();
  const [start, setStart] = useState<Start | null>(null);
  const [radius, setRadius] = useState(10);
  const [filter, setFilter] = useState<"all" | Source>("all");
  const [loopsOnly, setLoopsOnly] = useState(false);
  const [picking, setPicking] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const places = (prefs?.places ?? []) as { name: string; lat: number; lng: number }[];

  const q = useQuery<any>({
    queryKey: ["session-routes", session.id, start?.lat, start?.lng, radius],
    queryFn: () => api(`/training/sessions/${session.id}/routes`, { params: { ...(start ? { lat: start.lat, lng: start.lng, label: start.label } : {}), radius_km: radius } }),
    staleTime: 5 * 60_000,
  });
  const data = q.data;
  const all: any[] = data?.candidates ?? [];
  const shown = all.filter((c) => (filter === "all" || c.source === filter) && (!loopsOnly || c.loop !== false));
  const sel = all.find((c) => c.id === selected) ?? null;
  useEffect(() => { if (!selected && shown[0]) setSelected(shown[0].id); }, [data]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (data && data.start?.lat == null) setPicking(true); }, [data]);

  // Komoot routes get their line when selected (one request, cached on the server).
  const ref = sel && !sel.polyline ? (sel.source === "history" ? String(sel.activity_id) : sel.komoot_tour_id) : null;
  const geom = useQuery<{ polyline: string | null }>({
    queryKey: ["route-geom", sel?.source, ref], queryFn: () => api("/routes/geometry", { params: { source: sel.source, ref } }),
    enabled: Boolean(ref), staleTime: 86400_000,
  });
  const selPolyline = sel?.polyline || geom.data?.polyline || null;
  const mapRoutes = useMemo(() => {
    const lines = shown.filter((c) => c.polyline).slice(0, 12).map((c) => ({ id: c.id, points: decodePolyline(c.polyline) as [number, number][] }));
    if (sel && selPolyline && !sel.polyline) lines.push({ id: sel.id, points: decodePolyline(selPolyline) as [number, number][] });
    return lines;
  }, [shown, sel, selPolyline]);

  const attach = useMutation({
    mutationFn: () => api<any>(`/training/sessions/${session.id}/route`, { method: "PUT", body: { route: { ...sel, polyline: selPolyline } } }),
    onSuccess: (r) => { qc.setQueryData(["training-plan", planId], r.plan); toast(`Route attached: ${r.route.name}`); onClose(); },
    onError: (e: Error) => toast(e.message, true),
  });

  const t = data?.target;
  const st = data?.start;
  const counts = (s: Source) => all.filter((c) => c.source === s).length;
  return (
    <Modal title={<span className="row nowrap" style={{ gap: 8 }}><IconMap size={ICON.header} />Route for {session.title}</span>} onClose={onClose}
      footer={<>
        {sel?.komoot_url && <a className="btn" href={sel.komoot_url} target="_blank" rel="noreferrer"><BrandIcon provider="komoot" size={ICON.button} />Open in Komoot</a>}
        {!sel?.komoot_url && sel?.gpx_url && <a className="btn" href={sel.gpx_url}><IconDownload size={ICON.button} />GPX</a>}
        <button className="primary" disabled={!sel || attach.isPending} onClick={() => attach.mutate()}><IconCheck size={ICON.button} />Use this route</button>
      </>}>
      {/* what the session needs */}
      <div className="target-strip">
        <PlanSportIcon sport={session.sport} size={ICON.header} />
        {t ? <>
          <span><MetricIcon.distance size={ICON.inline} /><b>{num(t.distance_km, 1)} km</b>{t.distance_basis !== "plan" && <span className="muted"> (est.)</span>}</span>
          {t.elevation_gain_m > 0 && <span><MetricIcon.elevation size={ICON.inline} /><b>+{int(t.elevation_gain_m)} m</b></span>}
          {t.duration_s > 0 && <span><MetricIcon.time size={ICON.inline} />{duration(t.duration_s)}</span>}
        </> : <span className="muted small">Loading…</span>}
      </div>

      {/* where it starts */}
      <div className="row between nowrap" style={{ gap: 8 }}>
        <button className={`start-btn ${picking ? "on" : ""}`} onClick={() => setPicking(!picking)} aria-expanded={picking}>
          <IconPlaces size={ICON.button} /><span className="ellipsis">From {st?.label ?? "…"}</span><IconRight size={ICON.button} style={{ transform: picking ? "rotate(90deg)" : undefined }} />
        </button>
        <SegSelect label="Search radius" value={String(radius)} onChange={(v) => setRadius(Number(v))} options={RADII.map((r) => ({ value: String(r), label: `${r} km` }))} />
      </div>
      {picking && (
        <StartPicker current={start ?? (st?.lat != null ? st : null)} places={places}
          onPick={(s) => { setStart(s); setPicking(false); setSelected(null); }}
          onSaveHome={(s) => savePrefs.mutate({ places: [{ name: "Home", lat: s.lat, lng: s.lng, radius_km: 0.5 }, ...places.filter((p) => p.name.toLowerCase() !== "home")] })} />
      )}

      {q.isLoading ? <Skeleton h={300} /> : st?.lat == null ? (
        <Callout kind="info">Choose where you start — a saved place, your location or a search — to see routes nearby.</Callout>
      ) : (
        <>
          <RoutePreviewMap start={[st.lat, st.lng]} radiusKm={radius} routes={mapRoutes} selected={selected} onSelect={setSelected} />
          <div className="row between" style={{ gap: 8 }}>
            <div className="chips">
              <button className={`chip ${filter === "all" ? "on" : ""}`} onClick={() => setFilter("all")}>All {all.length}</button>
              {(Object.keys(SOURCE) as Source[]).filter((s) => counts(s) > 0).map((s) => (
                <button key={s} className={`chip ${filter === s ? "on" : ""}`} onClick={() => setFilter(s)}><SourceIcon source={s} size={ICON.button} />{SOURCE[s].short} {counts(s)}</button>
              ))}
            </div>
            <Switch checked={loopsOnly} onChange={setLoopsOnly} label={<span className="small">Loops only</span>} />
          </div>
          {Object.keys(data?.errors ?? {}).length > 0 && <p className="xs muted">Some Komoot routes could not be loaded right now.</p>}
          {!data?.komoot_connected && <p className="xs muted">Connect Komoot in Settings to also see your saved and suggested Komoot routes.</p>}

          {shown.length === 0 ? (
            <Empty title="No matching routes here" icon={IconMap}>
              <div className="row" style={{ justifyContent: "center" }}>
                {radius < 40 && <button className="sm" onClick={() => setRadius(RADII[RADII.indexOf(radius) + 1])}>Search {RADII[RADII.indexOf(radius) + 1]} km around</button>}
                {data?.planner_url && <a className="btn sm" href={data.planner_url} target="_blank" rel="noreferrer"><BrandIcon provider="komoot" size={ICON.button} />Plan one in Komoot</a>}
              </div>
            </Empty>
          ) : (
            <div className="route-list" role="radiogroup" aria-label="Suggested routes">
              {shown.map((c) => (
                <button key={c.id} role="radio" aria-checked={c.id === selected} className={`route-card ${c.id === selected ? "on" : ""}`} onClick={() => setSelected(c.id)}>
                  <Thumb c={c} />
                  <span className="route-body">
                    <span className="row between nowrap" style={{ gap: 8 }}>
                      <b className="ellipsis">{c.name}</b>
                      <span className="badge neutral" title={`Match ${c.match_score}/100`}>{fitLabel(c.match_score)}</span>
                    </span>
                    <span className="route-meta">
                      <SourceIcon source={c.source} />{SOURCE[c.source as Source].label}
                      {c.times_done > 1 && <> · done {c.times_done}×</>}
                      {c.last_done && <> · last {new Date(c.last_done).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "2-digit" })}</>}
                      {c.rating && <> · <IconKeySession size={ICON.inline} />{c.rating}{c.visitors ? ` · ${int(c.visitors)} people` : ""}</>}
                    </span>
                    <span className="route-stats">
                      <span><MetricIcon.distance size={ICON.inline} />{num(c.distance_km, 1)} km <Delta value={c.fit?.distance_pct} unit="%" tolerance={10} /></span>
                      <span><MetricIcon.elevation size={ICON.inline} />{int(c.elevation_gain_m)} m <Delta value={c.fit?.elevation_m} unit=" m" tolerance={Math.max(60, (t?.elevation_gain_m || 0) * 0.2)} /></span>
                      <span><IconPlaces size={ICON.inline} />{c.start_distance_km <= 0.3 ? "at the start" : `${num(c.start_distance_km, 1)} km away`}</span>
                      {c.loop === true && <span>Loop</span>}
                      {c.loop === false && <span>One way</span>}
                      {c.surface && <span>{c.surface}</span>}
                    </span>
                    {c.notes?.length > 0 && <span className="xs muted">{c.notes.join(" · ")}</span>}
                  </span>
                </button>
              ))}
            </div>
          )}
          {data?.planner_url && shown.length > 0 && (
            <a className="small row nowrap" style={{ gap: 4 }} href={data.planner_url} target="_blank" rel="noreferrer"><IconExternal size={ICON.inline} />Or draw your own in Komoot's planner</a>
          )}
        </>
      )}
    </Modal>
  );
}

/** The route chosen for a session: picture, numbers, and how to follow it. */
export function AttachedRoute({ route, onChange, onRemove }: { route: any; onChange: () => void; onRemove: () => void }) {
  return (
    <div className="attached-route">
      <Thumb c={route} size={48} />
      <span className="route-body">
        <b className="ellipsis">{route.name}</b>
        <span className="route-stats">
          <span><MetricIcon.distance size={ICON.inline} />{num(route.distance_km, 1)} km</span>
          <span><MetricIcon.elevation size={ICON.inline} />{int(route.elevation_gain_m)} m</span>
          {route.loop === true && <span>Loop</span>}
          <span className="row nowrap" style={{ gap: 3 }}><SourceIcon source={route.source} />{SOURCE[route.source as Source]?.label ?? "Route"}</span>
        </span>
      </span>
      <span className="row nowrap" style={{ gap: 2 }}>
        {route.komoot_url
          ? <a className="btn sm" href={route.komoot_url} target="_blank" rel="noreferrer" title="Open in Komoot to navigate"><BrandIcon provider="komoot" size={ICON.button} /><span className="hide-mobile">Navigate</span></a>
          : route.gpx_url ? <a className="btn sm" href={route.gpx_url} title="Download the route as GPX"><IconDownload size={ICON.button} /><span className="hide-mobile">GPX</span></a> : null}
        <Menu label="Route actions">
          <button onClick={onChange}><IconMap size={ICON.button} />Choose another route</button>
          <button className="danger" onClick={onRemove}><IconTrash size={ICON.button} />Remove route</button>
        </Menu>
      </span>
    </div>
  );
}

