import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { cssVar, familyColor } from "../lib/colors";

type MapStyle = "topo" | "osm" | "sat";

const LAYERS: Record<MapStyle, { label: string; url: string; attribution: string; maxZoom: number; invertDark: boolean }> = {
  topo: {
    label: "Topo",
    url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://openstreetmap.org">OSM</a>)',
    maxZoom: 17,
    invertDark: true,
  },
  osm: {
    label: "Street",
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 18,
    invertDark: true,
  },
  sat: {
    label: "Satellite",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Tiles &copy; Esri",
    maxZoom: 18,
    invertDark: false,
  },
};

const STYLE_KEY = "rp_map_style";
function loadStyle(): MapStyle {
  try {
    const v = localStorage.getItem(STYLE_KEY);
    if (v === "topo" || v === "osm" || v === "sat") return v;
  } catch { /* ignore */ }
  return "topo";
}
function isDark() {
  const t = document.documentElement.dataset.theme;
  return t === "dark" || (t !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
}
function isTouchDevice() {
  return typeof window !== "undefined" && window.matchMedia("(pointer: coarse)").matches;
}

function createMap(el: HTMLElement, style: MapStyle, interactive: boolean): { map: L.Map; tile: L.TileLayer } {
  const cfg = LAYERS[style];
  const map = L.map(el, {
    zoomControl: true,
    attributionControl: true,
    preferCanvas: true,
    dragging: interactive,
    scrollWheelZoom: false,
  });
  const tile = L.tileLayer(cfg.url, {
    attribution: cfg.attribution,
    maxZoom: cfg.maxZoom,
    className: cfg.invertDark && isDark() ? "dark-tiles" : "",
  }).addTo(map);
  return { map, tile };
}

function MapControls({ style, setStyle, touch, unlocked, setUnlocked }: {
  style: MapStyle;
  setStyle: (s: MapStyle) => void;
  touch: boolean;
  unlocked: boolean;
  setUnlocked: (u: boolean) => void;
}) {
  return (
    <div className="map-controls">
      {(Object.keys(LAYERS) as MapStyle[]).map((k) => (
        <button
          key={k}
          type="button"
          className={`map-pill ${style === k ? "on" : ""}`}
          onClick={() => {
            setStyle(k);
            try { localStorage.setItem(STYLE_KEY, k); } catch { /* ignore */ }
          }}
        >
          {LAYERS[k].label}
        </button>
      ))}
      {touch && (
        <button
          type="button"
          className={`map-pill ${unlocked ? "on" : ""}`}
          onClick={() => setUnlocked(!unlocked)}
        >
          {unlocked ? "Lock map" : "Pan map"}
        </button>
      )}
    </div>
  );
}

/** One activity track with optional hover marker and climb zoom. */
export function TrackMap({ points, highlight, climbs, focusClimb }: {
  points: [number, number][];
  highlight?: [number, number] | null;
  climbs?: [number, number][][];
  focusClimb?: [number, number][] | null;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const tile = useRef<L.TileLayer | null>(null);
  const marker = useRef<L.CircleMarker | null>(null);
  const touch = isTouchDevice();
  const [style, setStyle] = useState<MapStyle>(loadStyle);
  const [unlocked, setUnlocked] = useState(!touch);

  useEffect(() => {
    if (!el.current || points.length < 2) return;
    const { map: m, tile: tl } = createMap(el.current, style, unlocked);
    map.current = m;
    tile.current = tl;
    const accent = cssVar("--accent");
    const line = L.polyline(points, { color: accent, weight: 3.5, opacity: 0.95 }).addTo(m);
    (climbs || []).forEach((seg) => L.polyline(seg, { color: cssVar("--metric-climb"), weight: 5, opacity: 0.9 }).addTo(m));
    L.circleMarker(points[0], { radius: 6, color: "#fff", weight: 2, fillColor: cssVar("--good"), fillOpacity: 1 }).addTo(m).bindTooltip("Start");
    L.circleMarker(points[points.length - 1], { radius: 6, color: "#fff", weight: 2, fillColor: cssVar("--bad"), fillOpacity: 1 }).addTo(m).bindTooltip("Finish");
    marker.current = L.circleMarker(points[0], { radius: 7, color: "#fff", weight: 2, fillColor: accent, opacity: 0, fillOpacity: 0 }).addTo(m);
    m.fitBounds(line.getBounds(), { padding: [20, 20] });
    return () => { m.remove(); map.current = null; tile.current = null; };
  }, [points, climbs]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!map.current) return;
    const cfg = LAYERS[style];
    if (tile.current) tile.current.remove();
    tile.current = L.tileLayer(cfg.url, {
      attribution: cfg.attribution,
      maxZoom: cfg.maxZoom,
      className: cfg.invertDark && isDark() ? "dark-tiles" : "",
    }).addTo(map.current);
    tile.current.bringToBack();
  }, [style]);

  useEffect(() => {
    if (!map.current) return;
    if (unlocked) map.current.dragging.enable();
    else map.current.dragging.disable();
  }, [unlocked]);

  useEffect(() => {
    if (!map.current || !focusClimb || focusClimb.length < 2) return;
    map.current.fitBounds(L.latLngBounds(focusClimb), { padding: [32, 32], maxZoom: 16 });
  }, [focusClimb]);

  useEffect(() => {
    if (!marker.current) return;
    if (highlight) {
      marker.current.setLatLng(highlight);
      marker.current.setStyle({ opacity: 1, fillOpacity: 1 });
    } else {
      marker.current.setStyle({ opacity: 0, fillOpacity: 0 });
    }
  }, [highlight]);

  if (points.length < 2) return <div className="map empty">No GPS track</div>;
  return (
    <div className="map-wrap">
      <MapControls style={style} setStyle={setStyle} touch={touch} unlocked={unlocked} setUnlocked={setUnlocked} />
      <div className="map" ref={el} />
    </div>
  );
}

/** All routes drawn translucently — overlapping roads build up into a heatmap. */
export function RoutesMap({ routes, onSelect, opacity = 0.35, weight = 2 }: {
  routes: { id: number; family: string; points: [number, number][] }[];
  onSelect?: (id: number) => void;
  opacity?: number;
  weight?: number;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const tile = useRef<L.TileLayer | null>(null);
  const touch = isTouchDevice();
  const [style, setStyle] = useState<MapStyle>(loadStyle);
  const [unlocked, setUnlocked] = useState(!touch);

  useEffect(() => {
    if (!el.current) return;
    const { map: m, tile: tl } = createMap(el.current, style, unlocked);
    map.current = m;
    tile.current = tl;
    const renderer = L.canvas({ padding: 0.5 });
    const group = L.featureGroup();
    for (const r of routes) {
      if (r.points.length < 2) continue;
      const line = L.polyline(r.points, { color: cssVar(familyColor(r.family)), weight, opacity, renderer });
      if (onSelect) line.on("click", () => onSelect(r.id));
      group.addLayer(line);
    }
    group.addTo(m);
    if (group.getLayers().length) m.fitBounds(group.getBounds(), { padding: [20, 20] });
    else m.setView([47, 8], 5);
    return () => { m.remove(); map.current = null; tile.current = null; };
  }, [routes, onSelect, opacity, weight]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!map.current) return;
    const cfg = LAYERS[style];
    if (tile.current) tile.current.remove();
    tile.current = L.tileLayer(cfg.url, {
      attribution: cfg.attribution,
      maxZoom: cfg.maxZoom,
      className: cfg.invertDark && isDark() ? "dark-tiles" : "",
    }).addTo(map.current);
    tile.current.bringToBack();
  }, [style]);

  useEffect(() => {
    if (!map.current) return;
    if (unlocked) map.current.dragging.enable();
    else map.current.dragging.disable();
  }, [unlocked]);

  return (
    <div className="map-wrap">
      <MapControls style={style} setStyle={setStyle} touch={touch} unlocked={unlocked} setUnlocked={setUnlocked} />
      <div className="map tall" ref={el} />
    </div>
  );
}

/** Explorer tiles: every visited zoom-14 square, the largest cluster highlighted, max square outlined. */
export function TilesMap({ tiles, square }: { tiles: { bounds: [[number, number], [number, number]]; cluster: boolean }[]; square: [[number, number], [number, number]] | null }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const tile = useRef<L.TileLayer | null>(null);
  const touch = isTouchDevice();
  const [style, setStyle] = useState<MapStyle>(loadStyle);
  const [unlocked, setUnlocked] = useState(!touch);

  useEffect(() => {
    if (!el.current) return;
    const { map: m, tile: tl } = createMap(el.current, style, unlocked);
    map.current = m;
    tile.current = tl;
    const renderer = L.canvas({ padding: 0.5 });
    const group = L.featureGroup();
    // Amount, not identity: visited tiles quiet ink, the cluster dark ink.
    const accent = cssVar("--text-muted");
    const cluster = cssVar("--text-primary");
    for (const t of tiles) {
      group.addLayer(L.rectangle(t.bounds, { renderer, weight: 0.5, color: t.cluster ? cluster : accent, fillColor: t.cluster ? cluster : accent, fillOpacity: t.cluster ? 0.5 : 0.3 }));
    }
    group.addTo(m);
    if (square) L.rectangle(square, { color: cssVar("--text-primary"), weight: 2.5, fill: false, dashArray: "6 4" }).addTo(m).bindTooltip("Max square");
    if (group.getLayers().length) m.fitBounds(group.getBounds(), { padding: [20, 20] });
    else m.setView([47, 8], 5);
    return () => { m.remove(); map.current = null; tile.current = null; };
  }, [tiles, square]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!map.current) return;
    const cfg = LAYERS[style];
    if (tile.current) tile.current.remove();
    tile.current = L.tileLayer(cfg.url, {
      attribution: cfg.attribution,
      maxZoom: cfg.maxZoom,
      className: cfg.invertDark && isDark() ? "dark-tiles" : "",
    }).addTo(map.current);
    tile.current.bringToBack();
  }, [style]);

  useEffect(() => {
    if (!map.current) return;
    if (unlocked) map.current.dragging.enable();
    else map.current.dragging.disable();
  }, [unlocked]);

  return (
    <div className="map-wrap">
      <MapControls style={style} setStyle={setStyle} touch={touch} unlocked={unlocked} setUnlocked={setUnlocked} />
      <div className="map tall" ref={el} />
    </div>
  );
}

/** Tap the map to choose a point (used for Places). Shows existing places as faint circles. */
export function PlacePicker({ value, radiusKm, places, onPick }: {
  value: [number, number] | null; radiusKm: number; places: { name: string; lat: number; lng: number; radius_km: number }[];
  onPick: (lat: number, lng: number) => void;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const pick = useRef<L.Circle | null>(null);
  const cb = useRef(onPick);
  cb.current = onPick;
  useEffect(() => {
    if (!el.current) return;
    const { map: m } = createMap(el.current, "osm", true);
    map.current = m;
    const ink = cssVar("--text-muted");
    for (const p of places) L.circle([p.lat, p.lng], { radius: p.radius_km * 1000, color: ink, weight: 1, fillOpacity: 0.08 }).addTo(m).bindTooltip(p.name);
    const start = value ?? (places[0] ? [places[0].lat, places[0].lng] as [number, number] : null);
    if (start) m.setView(start, 13); else m.setView([47, 8], 5);
    m.on("click", (e: L.LeafletMouseEvent) => cb.current(Number(e.latlng.lat.toFixed(5)), Number(e.latlng.lng.toFixed(5))));
    return () => { m.remove(); map.current = null; pick.current = null; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    pick.current?.remove();
    pick.current = null;
    if (value) {
      pick.current = L.circle(value, { radius: Math.max(radiusKm, 0.05) * 1000, color: cssVar("--accent"), weight: 2, fillOpacity: 0.15 }).addTo(m);
      if (!m.getBounds().contains(value)) m.setView(value, 13);
    }
  }, [value?.[0], value?.[1], radiusKm]); // eslint-disable-line react-hooks/exhaustive-deps
  return <div ref={el} className="map" style={{ height: 240 }} aria-label="Tap the map to choose the place" />;
}

/** Route suggestions on one map: the start point, every route that has a line (quiet), and the selected
 *  one on top in the accent colour. Tapping a line selects it. */
export function RoutePreviewMap({ start, radiusKm, routes, selected, onSelect, height = 260 }: {
  start: [number, number];
  radiusKm: number;
  routes: { id: string; points: [number, number][] }[];
  selected: string | null;
  onSelect: (id: string) => void;
  height?: number;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const cb = useRef(onSelect);
  cb.current = onSelect;
  useEffect(() => {
    if (!el.current) return;
    const { map: m } = createMap(el.current, "osm", true);
    map.current = m;
    layer.current = L.layerGroup().addTo(m);
    m.setView(start, 12, { animate: false });
    // The map can mount inside an opening sheet: measure again once it has its size.
    const t = window.setTimeout(() => m.invalidateSize({ animate: false }), 250);
    return () => { window.clearTimeout(t); m.stop(); m.remove(); map.current = null; layer.current = null; };
  }, []); // one map for the sheet's lifetime; a new start only moves it
  useEffect(() => {
    const m = map.current;
    const g = layer.current;
    if (!m || !g) return;
    g.clearLayers();
    const quiet = cssVar("--text-muted");
    const accent = cssVar("--accent");
    L.circle(start, { radius: radiusKm * 1000, color: quiet, weight: 1, dashArray: "4 4", fill: false, interactive: false }).addTo(g);
    let sel: L.Polyline | null = null;
    for (const r of routes) {
      if (r.points.length < 2) continue;
      const isSel = r.id === selected;
      const line = L.polyline(r.points, { color: isSel ? accent : quiet, weight: isSel ? 5 : 3, opacity: isSel ? 1 : 0.55 });
      line.on("click", () => cb.current(r.id));
      line.addTo(g);
      if (isSel) sel = line;
    }
    sel?.bringToFront();
    L.circleMarker(start, { radius: 7, color: "#fff", weight: 2, fillColor: cssVar("--text-primary"), fillOpacity: 1 }).addTo(g).bindTooltip("Start");
    if (sel) m.fitBounds((sel as L.Polyline).getBounds().extend(start), { padding: [24, 24], maxZoom: 15, animate: false });
    else m.setView(start, 12, { animate: false });
  }, [routes, selected, start[0], start[1], radiusKm]); // eslint-disable-line react-hooks/exhaustive-deps
  return <div ref={el} className="map" style={{ height, minHeight: height, flex: "none" }} aria-label="Map of the suggested routes" />;
}
