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
export function RoutesMap({ routes, onSelect }: {
  routes: { id: number; family: string; points: [number, number][] }[];
  onSelect?: (id: number) => void;
}) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!el.current) return;
    const m = baseMap(el.current);
    const renderer = L.canvas({ padding: 0.5 });
    const group = L.featureGroup();
    for (const r of routes) {
      if (r.points.length < 2) continue;
      const line = L.polyline(r.points, { color: cssVar(familyColor(r.family)), weight: 2, opacity: 0.35, renderer });
      if (onSelect) line.on("click", () => onSelect(r.id));
      group.addLayer(line);
    }
    group.addTo(m);
    if (group.getLayers().length) m.fitBounds(group.getBounds(), { padding: [20, 20] });
    else m.setView([47, 8], 5);
    return () => { m.remove(); };
  }, [routes, onSelect]);
  return <div className="map tall" ref={el} />;
}
