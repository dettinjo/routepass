import { useEffect, useState } from "react";
import type { Place, Preferences } from "../lib/types";
import { useInstallPrompt, useTheme } from "../lib/pwa";
import { ICON, IconDownload, IconLocate, IconMap, IconPhone, IconPlus, IconTarget, IconTrash } from "./icons";
import { PlacePicker } from "./maps";
import { Card, SavedMark, Seg, useToast } from "./ui";

const GOALS: { key: string; label: string; unit: string }[] = [
  { key: "weekly_distance_km", label: "Distance per week", unit: "km" },
  { key: "weekly_time_hours", label: "Time per week", unit: "h" },
  { key: "monthly_distance_km", label: "Distance per month", unit: "km" },
  { key: "yearly_distance_km", label: "Distance per year", unit: "km" },
  { key: "yearly_elevation_m", label: "Climbing per year", unit: "m" },
];

/** Saves each goal when the field is left (no Save button, a quiet “Saved” mark instead). */
export function GoalsCard({ prefs, onSave, savedAt }: { prefs: Preferences; onSave: (g: Record<string, number | null>) => void; savedAt: number | null }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => setDraft(Object.fromEntries(GOALS.map((g) => [g.key, prefs.goals?.[g.key] != null ? String(prefs.goals[g.key]) : ""]))), [prefs.goals]);
  return (
    <Card title="Goals" icon={IconTarget} hint="Shown on Home with a projection; leave empty to skip" actions={<SavedMark at={savedAt} />}>
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
  const [point, setPoint] = useState<[number, number] | null>(null);
  const [radius, setRadius] = useState("0.5");
  const [adding, setAdding] = useState(places.length === 0);
  const locate = () => {
    if (!navigator.geolocation) return toast("This browser cannot share its location", true);
    navigator.geolocation.getCurrentPosition(
      (p) => setPoint([Number(p.coords.latitude.toFixed(5)), Number(p.coords.longitude.toFixed(5))]),
      () => toast("Location not available — tap the map instead", true),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  };
  const add = () => {
    if (!name.trim() || !point) return toast("Give the place a name and tap the map", true);
    const place = { name: name.trim(), lat: point[0], lng: point[1], radius_km: Number(radius) || 0.5 };
    onSave([...places.filter((p) => p.name.toLowerCase() !== place.name.toLowerCase()), place]);
    setName(""); setPoint(null); setAdding(false);
  };
  return (
    <Card title="Places" icon={IconMap} hint="For rules such as “starts near Home → don't copy”"
      actions={!adding && <button className="sm" onClick={() => setAdding(true)}><IconPlus size={ICON.button} />Add place</button>}>
      <div className="stack">
        {places.length > 0 && (
          <div className="list" style={{ border: "1px solid var(--border)", borderRadius: 12 }}>
            {places.map((p) => (
              <div key={p.name} className="item" style={{ cursor: "default" }}>
                <span className="card-ico"><IconMap size={ICON.header} /></span>
                <div className="main-col">
                  <b className="small">{p.name}</b>
                  <span className="meta">within {p.radius_km} km · <a href={`https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lng}#map=15/${p.lat}/${p.lng}`} target="_blank" rel="noreferrer">{p.lat.toFixed(4)}, {p.lng.toFixed(4)}</a></span>
                </div>
                <button className="ghost icon sm" aria-label={`Delete ${p.name}`} title="Delete" onClick={() => confirm(`Delete the place “${p.name}”? Rules using it stop matching.`) && onSave(places.filter((x) => x.name !== p.name))}><IconTrash size={ICON.button} /></button>
              </div>
            ))}
          </div>
        )}
        {adding && (
          <>
            <PlacePicker value={point} radiusKm={Number(radius) || 0.5} places={places} onPick={(lat, lng) => setPoint([lat, lng])} />
            <div className="fields">
              <label className="field">Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="Home" /></label>
              <label className="field">Radius (km)<input type="number" inputMode="decimal" step={0.1} min={0.1} value={radius} onChange={(e) => setRadius(e.target.value)} /></label>
            </div>
            <div className="row">
              <button className="sm" onClick={locate}><IconLocate size={ICON.button} />Use my location</button>
              <button className="sm primary" disabled={!name.trim() || !point} onClick={add}><IconPlus size={ICON.button} />Save place</button>
              {places.length > 0 && <button className="sm ghost" onClick={() => setAdding(false)}>Cancel</button>}
              <span className="xs muted">{point ? `${point[0]}, ${point[1]}` : "Tap the map to set the point"}</span>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

export function AppearanceCard() {
  const [theme, setTheme] = useTheme();
  const { canInstall, installed, install } = useInstallPrompt();
  return (
    <Card title="App" icon={IconPhone} hint="Install RoutePass on your phone's home screen; it opens like an app and shows recent data offline">
      <div className="stack">
        <div className="stack" style={{ gap: 6 }}>
          <span className="small secondary" style={{ fontWeight: 600 }}>Appearance</span>
          <Seg block value={theme} onChange={setTheme} options={[{ value: "system", label: "Automatic" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} />
        </div>
        {installed ? <span className="small muted">Installed as an app on this device.</span>
          : canInstall ? <div><button className="primary sm" onClick={install}><IconDownload size={ICON.button} />Install app</button></div>
            : <span className="small muted">To install: in Safari tap Share → “Add to Home Screen”; in Chrome use the menu → “Install app”.</span>}
      </div>
    </Card>
  );
}
