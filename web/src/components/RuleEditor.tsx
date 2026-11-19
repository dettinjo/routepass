import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { FAMILIES, FAMILY_LABEL, familyColor } from "../lib/colors";
import { activityDate, km } from "../lib/format";
import { useDebouncedCallback, usePrefs, useSportMeta } from "../lib/hooks";
import type { Rule } from "../lib/types";
import {
  BrandIcon, ICON, IconCalendar, IconCalendarStat, IconCheck, IconHome, IconInfo, IconPlaces, IconPlus, IconRight, IconSearch,
  IconStatusSkipped, IconX, MetricIcon, providerName, SportIcon,
} from "./icons";
import { Callout, Modal, Seg, useToast } from "./ui";

type Cond = Record<string, any>;
type Act = Record<string, any>;
type CondKey =
  | "sport" | "exclude_sports" | "distance_km" | "elevation_m" | "duration_min" | "weekdays" | "name"
  | "start_near" | "end_near" | "date" | "trainer" | "commute" | "has_heartrate" | "has_power";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const TOKENS = [
  { token: "{name}", label: "Name" }, { token: "{sport_label}", label: "Sport" }, { token: "{distance_km:.1f}", label: "Distance" },
  { token: "{elevation_m}", label: "Climb" }, { token: "{moving_time}", label: "Time" }, { token: "{date}", label: "Date" },
  { token: "{weekday}", label: "Weekday" }, { token: "{source}", label: "Source" },
];

/** Every condition the engine understands, as something a person can add with one tap. */
const CONDITIONS: { key: CondKey; label: string; icon: ComponentType<{ size?: number }>; keys: string[]; initial: Cond }[] = [
  { key: "sport", label: "Sport", icon: MetricIcon.count, keys: ["families", "sports"], initial: { families: [] } },
  { key: "exclude_sports", label: "Not these sports", icon: IconX, keys: ["exclude_sports"], initial: { exclude_sports: [] } },
  { key: "distance_km", label: "Distance", icon: MetricIcon.distance, keys: ["distance_km"], initial: { distance_km: {} } },
  { key: "elevation_m", label: "Climbing", icon: MetricIcon.elevation, keys: ["elevation_m"], initial: { elevation_m: {} } },
  { key: "duration_min", label: "Moving time", icon: MetricIcon.time, keys: ["duration_min"], initial: { duration_min: {} } },
  { key: "weekdays", label: "Day of week", icon: IconCalendar, keys: ["weekdays"], initial: { weekdays: [] } },
  { key: "name", label: "Name", icon: IconSearch, keys: ["name_contains", "name_regex"], initial: { name_contains: "" } },
  { key: "start_near", label: "Starts near", icon: IconPlaces, keys: ["start_near"], initial: { start_near: {} } },
  { key: "end_near", label: "Ends near", icon: IconPlaces, keys: ["end_near"], initial: { end_near: {} } },
  { key: "date", label: "Date range", icon: IconCalendarStat, keys: ["date"], initial: { date: {} } },
  { key: "trainer", label: "Indoor", icon: IconHome, keys: ["trainer"], initial: { trainer: true } },
  { key: "commute", label: "Commute", icon: MetricIcon.distance, keys: ["commute"], initial: { commute: true } },
  { key: "has_heartrate", label: "Heart rate", icon: MetricIcon.hr, keys: ["has_heartrate"], initial: { has_heartrate: true } },
  { key: "has_power", label: "Power", icon: MetricIcon.power, keys: ["has_power"], initial: { has_power: true } },
];
const condOf = (c: Cond) => CONDITIONS.filter((d) => d.keys.some((k) => k in c));

const RANGE_PRESETS: Record<string, { label: string; min?: number; max?: number }[]> = {
  distance_km: [{ label: "Under 2 km", max: 2 }, { label: "Under 10 km", max: 10 }, { label: "10–50 km", min: 10, max: 50 }, { label: "Over 50 km", min: 50 }],
  elevation_m: [{ label: "Flat (< 100 m)", max: 100 }, { label: "Over 500 m", min: 500 }, { label: "Over 1000 m", min: 1000 }],
  duration_min: [{ label: "Under 15 min", max: 15 }, { label: "Under 1 h", max: 60 }, { label: "Over 2 h", min: 120 }],
};
const UNIT: Record<string, string> = { distance_km: "km", elevation_m: "m", duration_min: "min" };

// ── wording ──────────────────────────────────────────────────────────────────
function rangeText(v: { min?: number; max?: number } | undefined, unit: string): string | null {
  if (!v || (v.min == null && v.max == null)) return null;
  if (v.min != null && v.max != null) return `${v.min}–${v.max} ${unit}`;
  return v.min != null ? `over ${v.min} ${unit}` : `under ${v.max} ${unit}`;
}

/** The conditions as short readable pieces, e.g. ["Ride", "under 5 km", "Sat/Sun"]. */
export function conditionPieces(c: Cond, sportLabel: (k: string) => string): string[] {
  const out: string[] = [];
  const sp = [...(c.families || []).map((f: string) => FAMILY_LABEL[f] ?? f), ...(c.sports || []).map(sportLabel)];
  if (sp.length) out.push(sp.join(" or "));
  if (c.exclude_sports?.length) out.push(`not ${c.exclude_sports.map(sportLabel).join(", ")}`);
  for (const k of ["distance_km", "elevation_m", "duration_min"]) {
    const t = rangeText(c[k], UNIT[k]);
    if (t) out.push(k === "elevation_m" ? `climbing ${t}` : t);
  }
  if (c.weekdays?.length) {
    const d = [...c.weekdays].sort();
    out.push(d.join() === "5,6" ? "weekends" : d.join() === "0,1,2,3,4" ? "weekdays" : d.map((i: number) => WEEKDAYS[i]).join("/"));
  }
  if (c.name_contains) out.push(`name has “${c.name_contains}”`);
  if (c.name_regex) out.push(`name matches /${c.name_regex}/`);
  for (const [k, word] of [["start_near", "starts"], ["end_near", "ends"]] as const) {
    const g = c[k];
    if (g && (g.place || g.lat != null)) out.push(`${word} near ${g.place ?? `${Number(g.lat).toFixed(3)}, ${Number(g.lng).toFixed(3)}`}`);
  }
  if (c.date?.from || c.date?.to) out.push(c.date.from && c.date.to ? `${c.date.from} – ${c.date.to}` : c.date.from ? `from ${c.date.from}` : `until ${c.date.to}`);
  const flags: [string, string, string][] = [["trainer", "indoor", "outdoor"], ["commute", "commute", "not a commute"], ["has_heartrate", "with heart rate", "without heart rate"], ["has_power", "with power", "without power"]];
  for (const [k, yes, no] of flags) if (c[k] != null) out.push(c[k] ? yes : no);
  return out;
}

export function actionText(a: Act, target: string): string {
  if (a.skip) return `Don't copy`;
  const extra = [
    a.name && "renamed",
    a.sport && `as ${a.sport}`,
    a.komoot?.visibility && a.komoot.visibility,
    a.strava?.hide_from_home && "muted in feed",
    a.strava?.commute && "as commute",
    (a.description || a.append_description) && "with description",
    a.strava?.gear_id && "with gear",
  ].filter(Boolean);
  return `Copy to ${providerName(target)}${extra.length ? ` · ${extra.join(", ")}` : ""}`;
}

/** One rule as a sentence of chips: If [Ride] [under 5 km] → Don't copy. */
export function RuleSentence({ rule, target, sportLabel }: { rule: Pick<Rule, "conditions" | "actions">; target: string; sportLabel: (k: string) => string }) {
  const pieces = conditionPieces(rule.conditions || {}, sportLabel);
  const skip = Boolean(rule.actions?.skip);
  return (
    <span className="rule-sentence">
      <span className="kw">{pieces.length ? "If" : "Every activity"}</span>
      {pieces.map((p, i) => <span key={i} className="cond-chip">{p}</span>)}
      <IconRight size={ICON.inline} className="muted" />
      <span className={`badge ${skip ? "neutral" : "outline"}`}>
        {skip ? <IconStatusSkipped size={ICON.inline} /> : <BrandIcon provider={target} size={ICON.inline} />}{actionText(rule.actions || {}, target)}
      </span>
    </span>
  );
}

// ── presets ──────────────────────────────────────────────────────────────────
export interface Preset { id: string; label: string; hint: string; icon: ComponentType<{ size?: number }>; conditions: Cond; actions: Act; needsPlace?: boolean }

export function presetsFor(direction: string, places: { name: string }[]): Preset[] {
  const toStrava = direction === "komoot_to_strava";
  const home = places[0]?.name;
  return [
    { id: "indoor", label: "Skip indoor sessions", hint: "Trainer and treadmill activities stay where they are", icon: IconHome, conditions: { trainer: true }, actions: { skip: true } },
    { id: "short", label: "Skip short activities", hint: "Anything under 2 km", icon: MetricIcon.distance, conditions: { distance_km: { max: 2 } }, actions: { skip: true } },
    { id: "gym", label: "Skip workouts without a route", hint: "Strength, yoga and other non-GPS sports", icon: MetricIcon.count, conditions: { families: ["other"] }, actions: { skip: true } },
    ...(home ? [{ id: "home", label: `Skip activities near ${home}`, hint: `Starts within the radius of “${home}”`, icon: IconPlaces, conditions: { start_near: { place: home } }, actions: { skip: true } }] : []),
    toStrava
      ? { id: "walks", label: "Copy walks and hikes quietly", hint: "Muted in your followers' feeds", icon: SportIconFor("walk"), conditions: { families: ["walk"] }, actions: { strava: { hide_from_home: true } } }
      : { id: "private", label: "Keep commutes private", hint: "Copied to Komoot as private tours", icon: MetricIcon.distance, conditions: { commute: true }, actions: { komoot: { visibility: "private" } } },
    { id: "tag", label: "Mark copies in the description", hint: `Adds “Synced from ${toStrava ? "Komoot" : "Strava"}”`, icon: IconInfo, conditions: {}, actions: { append_description: `Synced from ${toStrava ? "Komoot" : "Strava"}` } },
  ];
}
function SportIconFor(family: string) {
  return function I({ size }: { size?: number }) { return <SportIcon family={family} size={size} />; };
}

// ── editor pieces ─────────────────────────────────────────────────────────────
function RangeEditor({ k, value, onChange }: { k: string; value: { min?: number; max?: number }; onChange: (v: { min?: number; max?: number }) => void }) {
  const unit = UNIT[k];
  const num = (s: string) => (s === "" ? undefined : Number(s));
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="chips" style={{ flexWrap: "wrap" }}>
        {RANGE_PRESETS[k].map((p) => {
          const on = value.min === p.min && value.max === p.max;
          return <button key={p.label} type="button" className={`chip ${on ? "on" : ""}`} onClick={() => onChange({ min: p.min, max: p.max })}>{p.label}</button>;
        })}
      </div>
      <div className="row nowrap small secondary" style={{ gap: 6 }}>
        <span>between</span>
        <input type="number" inputMode="decimal" min={0} placeholder="any" value={value.min ?? ""} onChange={(e) => onChange({ ...value, min: num(e.target.value) })} aria-label={`Minimum ${unit}`} />
        <span>and</span>
        <input type="number" inputMode="decimal" min={0} placeholder="any" value={value.max ?? ""} onChange={(e) => onChange({ ...value, max: num(e.target.value) })} aria-label={`Maximum ${unit}`} />
        <span>{unit}</span>
      </div>
    </div>
  );
}

function SportPicker({ families, sports, onChange, all }: {
  families: string[]; sports: string[]; onChange: (f: string[], s: string[]) => void; all: { key: string; label: string; family: string }[];
}) {
  const [open, setOpen] = useState(sports.length > 0);
  const [q, setQ] = useState("");
  const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const shown = all.filter((s) => !q || s.label.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="chips" style={{ flexWrap: "wrap" }}>
        {FAMILIES.map((f) => (
          <button key={f} type="button" className={`chip ${families.includes(f) ? "on" : ""}`} onClick={() => onChange(toggle(families, f), sports)}>
            <SportIcon family={f} size={ICON.button} style={{ color: families.includes(f) ? undefined : familyColor(f) }} />{FAMILY_LABEL[f]}
          </button>
        ))}
      </div>
      {sports.length > 0 && (
        <div className="chips" style={{ flexWrap: "wrap" }}>
          {sports.map((s) => (
            <button key={s} type="button" className="chip on" onClick={() => onChange(families, sports.filter((x) => x !== s))} aria-label={`Remove ${s}`}>
              <SportIcon sport={s} size={ICON.button} />{all.find((x) => x.key === s)?.label ?? s}<IconX size={ICON.inline} />
            </button>
          ))}
        </div>
      )}
      <details className="more" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
        <summary><IconRight size={ICON.button} />Pick specific sports</summary>
        <div className="stack mt8" style={{ gap: 8 }}>
          <div className="search"><IconSearch size={ICON.button} /><input type="search" placeholder="Search sports" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <div className="sport-pick">
            {FAMILIES.map((f) => {
              const items = shown.filter((s) => s.family === f);
              if (!items.length) return null;
              return (
                <div key={f} className="stack" style={{ gap: 4 }}>
                  <span className="section-label">{FAMILY_LABEL[f]}</span>
                  <div className="chips" style={{ flexWrap: "wrap" }}>
                    {items.map((s) => (
                      <button key={s.key} type="button" className={`chip ${sports.includes(s.key) ? "on" : ""}`} onClick={() => onChange(families, toggle(sports, s.key))}>
                        <SportIcon sport={s.key} family={s.family} size={ICON.button} />{s.label}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </details>
    </div>
  );
}

function YesNo({ value, onChange, yes, no }: { value: boolean; onChange: (v: boolean) => void; yes: string; no: string }) {
  return <Seg value={value ? "yes" : "no"} onChange={(v) => onChange(v === "yes")} options={[{ value: "yes", label: yes }, { value: "no", label: no }]} />;
}

function TemplateInput({ value, onChange, placeholder, label }: { value: string; onChange: (v: string) => void; placeholder: string; label: string }) {
  return (
    <label className="field">{label}
      <input value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      <div className="chips" style={{ flexWrap: "wrap" }}>
        {TOKENS.map((t) => (
          <button key={t.token} type="button" className="chip token" onClick={() => onChange(`${value}${value && !value.endsWith(" ") ? " " : ""}${t.token}`)} title={`Insert ${t.token}`}>
            <IconPlus size={ICON.inline} />{t.label}
          </button>
        ))}
      </div>
    </label>
  );
}

function clean(o: Record<string, any>): Record<string, any> {
  const out: Record<string, any> = {};
  for (const [k, v] of Object.entries(o)) {
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length)) continue;
    if (typeof v === "object" && !Array.isArray(v)) {
      const inner = clean(v);
      if (Object.keys(inner).length) out[k] = inner;
    } else out[k] = v;
  }
  return out;
}

// ── the editor ────────────────────────────────────────────────────────────────
export function RuleEditor({ rule, direction, onClose, preset }: { rule: Partial<Rule> | null; direction: string; onClose: () => void; preset?: Preset | null }) {
  const { data: meta } = useSportMeta();
  const { data: prefs } = usePrefs();
  const places = prefs?.places ?? [];
  const qc = useQueryClient();
  const toast = useToast();
  const toKomoot = direction === "strava_to_komoot";
  const source = toKomoot ? "strava" : "komoot";
  const target = toKomoot ? "komoot" : "strava";
  const isNew = !rule?.id;
  const [step, setStep] = useState<"start" | "edit">(isNew && !preset ? "start" : "edit");
  const [name, setName] = useState(rule?.name ?? preset?.label ?? "");
  const [c, setC] = useState<Cond>(rule?.conditions ?? preset?.conditions ?? {});
  const [a, setA] = useState<Act>(rule?.actions ?? preset?.actions ?? {});
  const [adding, setAdding] = useState(false);
  const sportList = meta?.strava ?? [];
  const sportLabel = (k: string) => sportList.find((s) => s.key === k)?.label ?? k;
  const { data: gear } = useQuery<{ gear: { key: string; label: string }[] }>({ queryKey: ["gear-list"], queryFn: () => api("/insights/gear"), enabled: !toKomoot, staleTime: 300_000 });

  // Live dry run of the conditions against your recent activities.
  const [test, setTest] = useState<any>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const runTest = useDebouncedCallback((cond: Cond) => {
    api("/rules/test", { method: "POST", body: { direction, conditions: clean(cond), rule_id: rule?.id ?? null } })
      .then((r) => { setTest(r); setTestError(null); })
      .catch((e: Error) => setTestError(e.message));
  }, 450);
  const condKey = JSON.stringify(clean(c));
  useEffect(() => { if (step === "edit") runTest(c); }, [condKey, step]); // eslint-disable-line react-hooks/exhaustive-deps

  const autoName = useMemo(() => {
    const p = conditionPieces(clean(c), sportLabel);
    const what = p.length ? p.join(", ") : "Every activity";
    return `${what[0].toUpperCase()}${what.slice(1)} → ${a.skip ? "don't copy" : "copy"}`;
  }, [condKey, a.skip, sportList.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim() || autoName, direction, enabled: rule?.enabled ?? true, conditions: clean(c), actions: clean(a), ...(isNew ? { priority: 1000 } : {}) };
      return isNew ? api("/rules", { method: "POST", body }) : api(`/rules/${rule!.id}`, { method: "PUT", body });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["rules"] }); qc.invalidateQueries({ queryKey: ["preview"] }); toast("Rule saved"); onClose(); },
    onError: (e: Error) => toast(e.message, true),
  });

  const active = condOf(c);
  const addCond = (key: CondKey) => {
    const d = CONDITIONS.find((x) => x.key === key)!;
    setC({ ...c, ...d.initial });
    setAdding(false);
  };
  const removeCond = (key: CondKey) => {
    const d = CONDITIONS.find((x) => x.key === key)!;
    const next = { ...c };
    for (const k of d.keys) delete next[k];
    setC(next);
  };
  const set = (k: string, v: any) => setC({ ...c, [k]: v });

  const condBody = (key: CondKey): ReactNode => {
    switch (key) {
      case "sport":
        return <SportPicker all={sportList} families={c.families || []} sports={c.sports || []} onChange={(f, s) => setC({ ...c, families: f, sports: s })} />;
      case "exclude_sports":
        return <SportPicker all={sportList} families={[]} sports={c.exclude_sports || []} onChange={(_f, s) => set("exclude_sports", s)} />;
      case "distance_km": case "elevation_m": case "duration_min":
        return <RangeEditor k={key} value={c[key] || {}} onChange={(v) => set(key, v)} />;
      case "weekdays":
        return (
          <div className="stack" style={{ gap: 8 }}>
            <div className="chips" style={{ flexWrap: "wrap" }}>
              {WEEKDAYS.map((d, i) => (
                <button key={d} type="button" className={`chip ${(c.weekdays || []).includes(i) ? "on" : ""}`}
                  onClick={() => set("weekdays", (c.weekdays || []).includes(i) ? c.weekdays.filter((x: number) => x !== i) : [...(c.weekdays || []), i])}>{d}</button>
              ))}
            </div>
            <div className="row">
              <button type="button" className="sm ghost" onClick={() => set("weekdays", [0, 1, 2, 3, 4])}>Weekdays</button>
              <button type="button" className="sm ghost" onClick={() => set("weekdays", [5, 6])}>Weekend</button>
            </div>
          </div>
        );
      case "name": {
        const regex = "name_regex" in c;
        return (
          <div className="stack" style={{ gap: 8 }}>
            <Seg value={regex ? "regex" : "contains"} onChange={(v) => {
              const next = { ...c }; delete next.name_contains; delete next.name_regex;
              setC({ ...next, [v === "regex" ? "name_regex" : "name_contains"]: c.name_contains ?? c.name_regex ?? "" });
            }} options={[{ value: "contains", label: "Contains" }, { value: "regex", label: "Pattern" }]} />
            <input autoFocus placeholder={regex ? "^Commute|Pendeln" : "e.g. Commute"} value={(regex ? c.name_regex : c.name_contains) ?? ""}
              onChange={(e) => set(regex ? "name_regex" : "name_contains", e.target.value)} />
            {regex && <span className="xs muted">A regular expression, case-insensitive.</span>}
          </div>
        );
      }
      case "start_near": case "end_near":
        return places.length === 0 ? (
          <Callout kind="info">Save a place such as “Home” first in <Link to="/settings/profile">Settings → Profile & goals</Link>.</Callout>
        ) : (
          <div className="stack" style={{ gap: 8 }}>
            <div className="chips" style={{ flexWrap: "wrap" }}>
              {places.map((p) => (
                <button key={p.name} type="button" className={`chip ${c[key]?.place === p.name ? "on" : ""}`} onClick={() => set(key, { place: p.name, radius_km: c[key]?.radius_km })}>
                  <IconPlaces size={ICON.button} />{p.name}
                </button>
              ))}
            </div>
            {c[key]?.place && (
              <div className="row nowrap small secondary" style={{ gap: 6 }}>
                <span>within</span>
                <input type="number" inputMode="decimal" step={0.1} min={0.1} style={{ width: 90 }} placeholder={String(places.find((p) => p.name === c[key].place)?.radius_km ?? 1)}
                  value={c[key]?.radius_km ?? ""} onChange={(e) => set(key, { ...c[key], radius_km: e.target.value ? Number(e.target.value) : undefined })} />
                <span>km (empty: the place's own radius)</span>
              </div>
            )}
          </div>
        );
      case "date":
        return (
          <div className="fields">
            <label className="field">From<input type="date" value={c.date?.from ?? ""} onChange={(e) => set("date", { ...(c.date || {}), from: e.target.value || undefined })} /></label>
            <label className="field">Until<input type="date" value={c.date?.to ?? ""} onChange={(e) => set("date", { ...(c.date || {}), to: e.target.value || undefined })} /></label>
          </div>
        );
      case "trainer": return <YesNo value={c.trainer} onChange={(v) => set("trainer", v)} yes="Indoor" no="Outdoor" />;
      case "commute": return <YesNo value={c.commute} onChange={(v) => set("commute", v)} yes="Commute" no="Not a commute" />;
      case "has_heartrate": return <YesNo value={c.has_heartrate} onChange={(v) => set("has_heartrate", v)} yes="Recorded" no="Not recorded" />;
      case "has_power": return <YesNo value={c.has_power} onChange={(v) => set("has_power", v)} yes="Recorded" no="Not recorded" />;
    }
  };

  const title = <span className="row nowrap" style={{ gap: 6 }}>{isNew ? "New rule" : "Edit rule"} <span className="badge neutral"><BrandIcon provider={source} size={ICON.inline} /><IconRight size={ICON.inline} /><BrandIcon provider={target} size={ICON.inline} /></span></span>;

  if (step === "start") {
    return (
      <Modal title={title} onClose={onClose}>
        <p className="small secondary">Start from a common rule, or build your own. You can change everything afterwards.</p>
        <div className="preset-grid">
          {presetsFor(direction, places).map((p) => (
            <button key={p.id} type="button" className="preset" onClick={() => { setName(p.label); setC(p.conditions); setA(p.actions); setStep("edit"); }}>
              <span className="card-ico"><p.icon size={ICON.header} /></span>
              <span><b>{p.label}</b><span className="xs muted">{p.hint}</span></span>
            </button>
          ))}
          <button type="button" className="preset blank" onClick={() => setStep("edit")}>
            <span className="card-ico"><IconPlus size={ICON.header} /></span>
            <span><b>Start from scratch</b><span className="xs muted">Choose conditions and what happens</span></span>
          </button>
        </div>
      </Modal>
    );
  }

  const remaining = CONDITIONS.filter((d) => !active.includes(d));
  return (
    <Modal title={title} onClose={onClose}
      footer={<><button onClick={onClose}>Cancel</button><button className="primary" disabled={save.isPending} onClick={() => save.mutate()}><IconCheck size={ICON.button} />Save rule</button></>}>
      {/* IF */}
      <section className="rule-block">
        <div className="rule-kw">If</div>
        <div className="stack" style={{ gap: 10 }}>
          {active.length === 0 && <p className="small secondary">Every {providerName(source)} activity — add a condition to narrow it down.</p>}
          {active.map((d, i) => (
            <div key={d.key} className="cond-row">
              <div className="cond-head">
                {i > 0 && <span className="and">and</span>}
                <d.icon size={ICON.button} /><b>{d.label}</b>
                <button type="button" className="ghost icon sm" onClick={() => removeCond(d.key)} aria-label={`Remove ${d.label}`}><IconX size={ICON.button} /></button>
              </div>
              {condBody(d.key)}
            </div>
          ))}
          {adding ? (
            <div className="add-grid" role="group" aria-label="Add a condition">
              {remaining.map((d) => (
                <button key={d.key} type="button" className="chip" onClick={() => addCond(d.key)}><d.icon size={ICON.button} />{d.label}</button>
              ))}
              <button type="button" className="chip" onClick={() => setAdding(false)}><IconX size={ICON.button} />Cancel</button>
            </div>
          ) : (
            remaining.length > 0 && <div><button type="button" className="sm" onClick={() => setAdding(true)}><IconPlus size={ICON.button} />Add condition</button></div>
          )}
        </div>
      </section>

      {/* THEN */}
      <section className="rule-block">
        <div className="rule-kw">Then</div>
        <div className="stack" style={{ gap: 10 }}>
          <div className="choice-pair" role="radiogroup" aria-label="What happens">
            <button type="button" role="radio" aria-checked={!a.skip} className={!a.skip ? "on" : ""} onClick={() => setA({ ...a, skip: undefined })}>
              <BrandIcon provider={target} size={ICON.header} /><span><b>Copy to {providerName(target)}</b><span className="xs muted">Create it there if it is missing</span></span>
            </button>
            <button type="button" role="radio" aria-checked={Boolean(a.skip)} className={a.skip ? "on" : ""} onClick={() => setA({ skip: true })}>
              <IconStatusSkipped size={ICON.header} /><span><b>Don't copy</b><span className="xs muted">Leave it only on {providerName(source)}</span></span>
            </button>
          </div>
          {!a.skip && (
            <details className="more" open={Object.keys(clean({ ...a, skip: undefined })).length > 0}>
              <summary><IconRight size={ICON.button} />Change how the copy looks</summary>
              <div className="stack mt8" style={{ gap: 12 }}>
                <TemplateInput label="Title" placeholder="Same as the original" value={a.name ?? ""} onChange={(v) => setA({ ...a, name: v || undefined })} />
                <label className="field">{toKomoot ? "Komoot sport" : "Strava sport type"}
                  <select value={a.sport ?? ""} onChange={(e) => setA({ ...a, sport: e.target.value || undefined })}>
                    <option value="">Matched automatically</option>
                    {(toKomoot ? meta?.komoot : meta?.strava)?.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                  </select>
                </label>
                {toKomoot ? (
                  <label className="field">Visibility on Komoot
                    <Seg value={a.komoot?.visibility ?? ""} onChange={(v) => setA({ ...a, komoot: v ? { visibility: v } : undefined })}
                      options={[{ value: "", label: "Default" }, { value: "private", label: "Private" }, { value: "friends", label: "Friends" }, { value: "public", label: "Public" }]} />
                  </label>
                ) : (
                  <div className="stack" style={{ gap: 10 }}>
                    <label className="row nowrap small" style={{ gap: 8, cursor: "pointer" }}><input type="checkbox" checked={Boolean(a.strava?.hide_from_home)} onChange={(e) => setA({ ...a, strava: { ...(a.strava || {}), hide_from_home: e.target.checked || undefined } })} />Mute in followers' feeds</label>
                    <label className="row nowrap small" style={{ gap: 8, cursor: "pointer" }}><input type="checkbox" checked={Boolean(a.strava?.commute)} onChange={(e) => setA({ ...a, strava: { ...(a.strava || {}), commute: e.target.checked || undefined } })} />Mark as commute</label>
                    <label className="field">Gear
                      <select value={a.strava?.gear_id ?? ""} onChange={(e) => setA({ ...a, strava: { ...(a.strava || {}), gear_id: e.target.value || undefined } })}>
                        <option value="">Strava's default</option>
                        {(gear?.gear || []).map((g) => <option key={g.key} value={g.key}>{g.label}</option>)}
                        {a.strava?.gear_id && !(gear?.gear || []).some((g) => g.key === a.strava.gear_id) && <option value={a.strava.gear_id}>{a.strava.gear_id}</option>}
                      </select>
                    </label>
                  </div>
                )}
                <TemplateInput label="Add to the description" placeholder={`e.g. Synced from ${providerName(source)}`} value={a.append_description ?? ""} onChange={(v) => setA({ ...a, append_description: v || undefined })} />
                <TemplateInput label="Replace the description" placeholder="Keep the original" value={a.description ?? ""} onChange={(v) => setA({ ...a, description: v || undefined })} />
              </div>
            </details>
          )}
        </div>
      </section>

      {/* What it would do */}
      <section className="rule-test" aria-live="polite">
        {testError ? <Callout kind="bad">{testError}</Callout> : !test ? <span className="small muted">Checking your recent activities…</span> : (
          <>
            <div className="row between nowrap">
              <b>{test.matched === 0 ? "Matches none" : `Matches ${test.matched}`} of your last {test.considered} {providerName(source)} activities</b>
            </div>
            {test.shadowed_by.length > 0 && (
              <p className="small secondary">
                {test.effective} would follow this rule — {test.shadowed_by.map((s: any) => `${s.count} already go by “${s.name}”`).join(", ")} (it comes first).
              </p>
            )}
            {test.samples.length > 0 && (
              <div className="list">
                {test.samples.slice(0, 5).map((s: any) => (
                  <div key={s.activity_id} className="item" style={{ cursor: "default", padding: "8px 0", opacity: s.decided_by ? 0.55 : 1 }}>
                    <SportIcon sport={s.sport} family={s.family} size={ICON.header} style={{ color: familyColor(s.family) }} />
                    <div className="main-col"><span className="small ellipsis"><b>{s.name}</b></span><span className="meta">{activityDate(s, false)}{s.distance_m ? ` · ${km(s.distance_m)} km` : ""}{s.decided_by ? ` · goes by “${s.decided_by}”` : ""}</span></div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </section>

      <label className="field">Rule name<input value={name} onChange={(e) => setName(e.target.value)} placeholder={autoName} /></label>
    </Modal>
  );
}
