import { useEffect, useState } from "react";
import type { Place, Preferences } from "../lib/types";
import { useInstallPrompt, useTheme } from "../lib/pwa";
import { IconDownload, IconMap, IconPlus, IconTarget, IconTrash, MetricIcon } from "./icons";
import { Card, Seg, useToast } from "./ui";

const GOALS: { key: string; label: string; unit: string }[] = [
  { key: "weekly_distance_km", label: "Distance per week", unit: "km" },
  { key: "weekly_time_hours", label: "Time per week", unit: "h" },
  { key: "monthly_distance_km", label: "Distance per month", unit: "km" },
  { key: "yearly_distance_km", label: "Distance per year", unit: "km" },
  { key: "yearly_elevation_m", label: "Climbing per year", unit: "m" },
];

export function GoalsCard({ prefs, onSave }: { prefs: Preferences; onSave: (g: Record<string, number | null>) => void }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => setDraft(Object.fromEntries(GOALS.map((g) => [g.key, prefs.goals?.[g.key] != null ? String(prefs.goals[g.key]) : ""]))), [prefs.goals]);
  return (
    <Card title="Goals" icon={IconTarget} hint="Shown on Home with a projection; leave empty to skip">
      <div className="fields">
        {GOALS.map((g) => (
          <label key={g.key} className="field">{g.label} ({g.unit})
            <input type="number" inputMode="decimal" min={0} value={draft[g.key] ?? ""}
              onChange={(e) => setDraft({ ...draft, [g.key]: e.target.value })}
              onBlur={() => {
                const v = draft[g.key] === "" ? null : Number(draft[g.key]);
                if (v !== (prefs.goals?.[g.key] ?? null)) onSave({ [g.key]: v });
              }} />
          </label>
        ))}
      </div>
    </Card>
  );
}

export function PlacesCard({ places, onSave }: { places: Place[]; onSave: (p: Place[]) => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [radius, setRadius] = useState("0.5");
  const locate = () => {
    if (!navigator.geolocation) return toast("This browser cannot share its location", true);
    navigator.geolocation.getCurrentPosition(
      (p) => { setLat(p.coords.latitude.toFixed(5)); setLng(p.coords.longitude.toFixed(5)); },
      () => toast("Location not available — enter coordinates instead", true),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  };
  const add = () => {
    const place = { name: name.trim(), lat: Number(lat), lng: Number(lng), radius_km: Number(radius) || 0.5 };
    if (!place.name || !Number.isFinite(place.lat) || !Number.isFinite(place.lng)) return toast("Name and coordinates are required", true);
    onSave([...places.filter((p) => p.name.toLowerCase() !== place.name.toLowerCase()), place]);
    setName(""); setLat(""); setLng("");
  };
  return (
    <Card title="Places" icon={IconMap} hint="For rules such as “starts near Home → don't copy”">
      <div className="stack">
        {places.length > 0 && (
          <div className="list" style={{ border: "1px solid var(--border)", borderRadius: 12 }}>
            {places.map((p) => (
              <div key={p.name} className="item" style={{ cursor: "default" }}>
                <span className="card-ico"><IconMap size={16} /></span>
                <div className="main-col">
                  <b className="small">{p.name}</b>
                  <span className="meta">{p.lat.toFixed(4)}, {p.lng.toFixed(4)} · within {p.radius_km} km</span>
                </div>
                <a className="xs" href={`https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lng}#map=15/${p.lat}/${p.lng}`} target="_blank" rel="noreferrer">map</a>
                <button className="ghost icon sm danger" aria-label={`Delete ${p.name}`} onClick={() => onSave(places.filter((x) => x.name !== p.name))}><IconTrash size={16} /></button>
              </div>
            ))}
          </div>
        )}
        <div className="fields">
          <label className="field">Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="Home" /></label>
          <label className="field">Radius (km)<input type="number" inputMode="decimal" step={0.1} min={0.1} value={radius} onChange={(e) => setRadius(e.target.value)} /></label>
          <label className="field">Latitude<input inputMode="decimal" value={lat} onChange={(e) => setLat(e.target.value)} /></label>
          <label className="field">Longitude<input inputMode="decimal" value={lng} onChange={(e) => setLng(e.target.value)} /></label>
        </div>
        <div className="row">
          <button className="sm" onClick={locate}><MetricIcon.distance size={15} />Use my location</button>
          <button className="sm primary" onClick={add}><IconPlus size={15} />Save place</button>
        </div>
      </div>
    </Card>
  );
}

export function AppearanceCard() {
  const [theme, setTheme] = useTheme();
  const { canInstall, installed, install } = useInstallPrompt();
  return (
    <Card title="App" icon={IconDownload} hint="Install RoutePass on your phone's home screen; it opens like an app and shows recent data offline">
      <div className="stack">
        <div className="stack" style={{ gap: 6 }}>
          <span className="small secondary">Appearance</span>
          <Seg block value={theme} onChange={setTheme} options={[{ value: "system", label: "Automatic" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} />
        </div>
        {installed ? <span className="small muted">Installed as an app on this device.</span>
          : canInstall ? <div><button className="primary sm" onClick={install}><IconDownload size={15} />Install app</button></div>
          : <span className="small muted">To install: in Safari tap Share → “Add to Home Screen”; in Chrome use the menu → “Install app”.</span>}
      </div>
    </Card>
  );
}
