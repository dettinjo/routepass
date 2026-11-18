import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { cssVar, familyColor } from "../lib/colors";

const TILES = {
  url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
};
function isDark() {
  const t = document.documentElement.dataset.theme;
  return t === "dark" || (t !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
}

function baseMap(el: HTMLElement): L.Map {
  const map = L.map(el, { zoomControl: true, attributionControl: true, preferCanvas: true });
  L.tileLayer(TILES.url, { attribution: TILES.attribution, maxZoom: 18, className: isDark() ? "dark-tiles" : "" }).addTo(map);
  return map;
}

/** One activity track with an optional hover marker driven by the charts. */
export function TrackMap({ points, highlight, climbs }: {
  points: [number, number][];
  highlight?: [number, number] | null;
  climbs?: [number, number][][];
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const marker = useRef<L.CircleMarker | null>(null);

  useEffect(() => {
    if (!el.current || points.length < 2) return;
    const m = baseMap(el.current);
    map.current = m;
    const accent = cssVar("--accent");
    const line = L.polyline(points, { color: accent, weight: 3.5, opacity: 0.95 }).addTo(m);
    (climbs || []).forEach((seg) => L.polyline(seg, { color: cssVar("--series-2"), weight: 5, opacity: 0.9 }).addTo(m));
    L.circleMarker(points[0], { radius: 6, color: "#fff", weight: 2, fillColor: cssVar("--good"), fillOpacity: 1 }).addTo(m).bindTooltip("Start");
    L.circleMarker(points[points.length - 1], { radius: 6, color: "#fff", weight: 2, fillColor: cssVar("--bad"), fillOpacity: 1 }).addTo(m).bindTooltip("Finish");
    marker.current = L.circleMarker(points[0], { radius: 7, color: "#fff", weight: 2, fillColor: accent, opacity: 0, fillOpacity: 0 }).addTo(m);
    m.fitBounds(line.getBounds(), { padding: [20, 20] });
    return () => { m.remove(); map.current = null; };
  }, [points, climbs]);

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
  return <div className="map" ref={el} />;
}

/** All routes drawn translucently — overlapping roads build up into a heatmap. */
export function RoutesMap({ routes, onSelect, opacity = 0.35, weight = 2 }: {
  routes: { id: number; family: string; points: [number, number][] }[];
  onSelect?: (id: number) => void;
  opacity?: number;
  weight?: number;
}) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!el.current) return;
    const m = baseMap(el.current);
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
    return () => { m.remove(); };
  }, [routes, onSelect, opacity, weight]);
  return <div className="map tall" ref={el} />;
}

/** Explorer tiles: every visited zoom-14 square, the largest cluster highlighted, max square outlined. */
export function TilesMap({ tiles, square }: { tiles: { bounds: [[number, number], [number, number]]; cluster: boolean }[]; square: [[number, number], [number, number]] | null }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!el.current) return;
    const m = baseMap(el.current);
    const renderer = L.canvas({ padding: 0.5 });
    const group = L.featureGroup();
    const accent = cssVar("--accent");
    const cluster = cssVar("--series-2");
    for (const t of tiles) {
      group.addLayer(L.rectangle(t.bounds, { renderer, weight: 0.5, color: t.cluster ? cluster : accent, fillColor: t.cluster ? cluster : accent, fillOpacity: t.cluster ? 0.5 : 0.3 }));
    }
    group.addTo(m);
    if (square) L.rectangle(square, { color: cssVar("--text-primary"), weight: 2.5, fill: false, dashArray: "6 4" }).addTo(m).bindTooltip("Max square");
    if (group.getLayers().length) m.fitBounds(group.getBounds(), { padding: [20, 20] });
    else m.setView([47, 8], 5);
    return () => { m.remove(); };
  }, [tiles, square]);
  return <div className="map tall" ref={el} />;
}
