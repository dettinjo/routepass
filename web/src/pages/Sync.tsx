import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  BrandIcon, IconArrowDown, IconArrowUp, IconCheck, IconHistory, IconImport, IconList, IconPlay, IconPlus,
  IconRefresh, IconRight, IconSettings, IconSync, IconTrash, IconWarn, IconX, providerName,
} from "../components/icons";
import { Callout, Card, Empty, Modal, Seg, Skeleton, StatusBadge, Switch, useToast } from "../components/ui";
import { api } from "../lib/api";
import { FAMILIES, FAMILY_LABEL } from "../lib/colors";
import { activityDate, ago, dateTime, int, km } from "../lib/format";
import { usePrefs, useRunSync, useSavePrefs, useSportMeta, useStatus } from "../lib/hooks";
import type { Rule, SyncJob, SyncRun } from "../lib/types";

const DIRS = [
  { key: "komoot_to_strava", from: "komoot", to: "strava" },
  { key: "strava_to_komoot", from: "strava", to: "komoot" },
] as const;
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const TEMPLATE_HELP = "{name} {sport_label} {distance_km:.1f} {elevation_m} {duration_min} {moving_time} {date} {time} {weekday} {source}";
const dirTitle = (d: { from: string; to: string }) => (
  <span className="row nowrap" style={{ gap: 6 }}><BrandIcon provider={d.from} size={18} />{providerName(d.from)}<IconRight size={15} /><BrandIcon provider={d.to} size={18} />{providerName(d.to)}</span>
);

function useMut(path: (v: any) => string, method = "POST", invalidate: string[][] = [["rules"], ["jobs"], ["status"]]) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (v: any) => api(path(v), { method, body: v?.body }),
    onSuccess: () => invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k })),
    onError: (e: Error) => toast(e.message, true),
  });
}

function summarize(r: Rule): string {
  const c = r.conditions || {};
  const parts: string[] = [];
  if (c.sports?.length) parts.push(c.sports.join(", "));
  if (c.families?.length) parts.push(c.families.map((f: string) => FAMILY_LABEL[f]).join(", "));
  if (c.exclude_sports?.length) parts.push(`not ${c.exclude_sports.join(", ")}`);
  const rng = (k: string, u: string) => {
    const v = c[k];
    if (!v) return;
    if (v.min != null && v.max != null) parts.push(`${v.min}–${v.max} ${u}`);
    else if (v.min != null) parts.push(`≥ ${v.min} ${u}`);
    else if (v.max != null) parts.push(`≤ ${v.max} ${u}`);
  };
  rng("distance_km", "km"); rng("elevation_m", "m"); rng("duration_min", "min");
  if (c.name_contains) parts.push(`name has “${c.name_contains}”`);
  if (c.name_regex) parts.push(`name ~ /${c.name_regex}/`);
  if (c.weekdays?.length) parts.push(c.weekdays.map((d: number) => WEEKDAYS[d]).join("/"));
  if (c.date?.from || c.date?.to) parts.push(`${c.date.from ?? "…"} → ${c.date.to ?? "…"}`);
  for (const f of ["commute", "trainer", "has_heartrate", "has_power"]) if (c[f] != null) parts.push(`${c[f] ? "" : "not "}${f.replace("has_", "with ")}`);
  const a = r.actions || {};
  const act = a.skip ? "skip" : [
    "sync",
    a.name && `rename “${a.name}”`,
    a.sport && `as ${a.sport}`,
    a.komoot?.visibility && `${a.komoot.visibility}`,
    a.strava?.hide_from_home && "muted in feed",
  ].filter(Boolean).join(", ");
  return `${parts.length ? "If " + parts.join(" · ") : "Every activity"} → ${act}`;
}

function TriState({ value, onChange, label }: { value: boolean | undefined; onChange: (v: boolean | undefined) => void; label: string }) {
  return (
    <label className="field">{label}
      <select value={value === undefined ? "" : value ? "yes" : "no"} onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value === "yes")}>
        <option value="">Any</option><option value="yes">Yes</option><option value="no">No</option>
      </select>
    </label>
  );
}

function MultiChips({ options, value, onChange }: { options: { key: string; label: string }[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="row" style={{ gap: 6 }}>
      {options.map((o) => (
        <button type="button" key={o.key} className={`chip ${value.includes(o.key) ? "on" : ""}`}
          onClick={() => onChange(value.includes(o.key) ? value.filter((x) => x !== o.key) : [...value, o.key])}>{o.label}</button>
      ))}
    </div>
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

function RuleEditor({ rule, direction, onClose }: { rule: Partial<Rule> | null; direction: string; onClose: () => void }) {
  const { data: meta } = useSportMeta();
  const qc = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(rule?.name ?? "");
  const [enabled, setEnabled] = useState(rule?.enabled ?? true);
  const [c, setC] = useState<Record<string, any>>(rule?.conditions ?? {});
  const [a, setA] = useState<Record<string, any>>(rule?.actions ?? {});
  const [showAllSports, setShowAllSports] = useState(false);
  const toKomoot = direction === "strava_to_komoot";
  const setCond = (k: string, v: any) => setC({ ...c, [k]: v });
  const setRange = (k: string, side: "min" | "max", v: string) => setC({ ...c, [k]: { ...(c[k] || {}), [side]: v === "" ? undefined : Number(v) } });
  const save = useMutation({
    mutationFn: () => {
      const body = { name, direction, enabled, conditions: clean(c), actions: clean(a), ...(rule?.id ? {} : { priority: 1000 }) };
      return rule?.id ? api(`/rules/${rule.id}`, { method: "PUT", body }) : api("/rules", { method: "POST", body });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["rules"] }); toast("Rule saved"); onClose(); },
    onError: (e: Error) => toast(e.message, true),
  });
  const sports = (meta?.strava || []).map((s) => ({ key: s.key, label: s.label }));
  const shownSports = showAllSports ? sports : sports.slice(0, 14);
  const range = (k: string, label: string) => (
    <label className="field">{label}
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <input type="number" placeholder="min" value={c[k]?.min ?? ""} onChange={(e) => setRange(k, "min", e.target.value)} />
        <input type="number" placeholder="max" value={c[k]?.max ?? ""} onChange={(e) => setRange(k, "max", e.target.value)} />
      </div>
    </label>
  );
  return (
    <Modal title={rule?.id ? "Edit rule" : "New rule"} onClose={onClose}
      footer={<><button onClick={onClose}>Cancel</button><button className="primary" disabled={!name || save.isPending} onClick={() => save.mutate()}>Save rule</button></>}>
      <div className="row" style={{ gap: 16 }}>
        <label className="field" style={{ flex: 1 }}>Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Long rides as private tours" autoFocus /></label>
        <Switch checked={enabled} onChange={setEnabled} label="Enabled" />
      </div>

      <div className="section-label">When all of these match</div>
      <label className="field">Sports (any of)
        <MultiChips options={shownSports} value={c.sports || []} onChange={(v) => setCond("sports", v)} />
        {sports.length > 14 && <button type="button" className="sm ghost" style={{ alignSelf: "flex-start" }} onClick={() => setShowAllSports(!showAllSports)}>{showAllSports ? "Fewer" : "All sports"}</button>}
      </label>
      <label className="field">Families (any of)
        <MultiChips options={FAMILIES.map((f) => ({ key: f, label: FAMILY_LABEL[f] }))} value={c.families || []} onChange={(v) => setCond("families", v)} />
      </label>
      <div className="fields">
        {range("distance_km", "Distance (km)")}
        {range("elevation_m", "Elevation gain (m)")}
        {range("duration_min", "Moving time (min)")}
      </div>
      <div className="fields">
        <label className="field">Name contains<input value={c.name_contains ?? ""} onChange={(e) => setCond("name_contains", e.target.value || undefined)} /></label>
        <label className="field">Name matches regex<input value={c.name_regex ?? ""} onChange={(e) => setCond("name_regex", e.target.value || undefined)} placeholder="^Commute" /></label>
        <label className="field">From date<input type="date" value={c.date?.from ?? ""} onChange={(e) => setCond("date", { ...(c.date || {}), from: e.target.value || undefined })} /></label>
        <label className="field">To date<input type="date" value={c.date?.to ?? ""} onChange={(e) => setCond("date", { ...(c.date || {}), to: e.target.value || undefined })} /></label>
      </div>
      <label className="field">Weekdays
        <MultiChips options={WEEKDAYS.map((d, i) => ({ key: String(i), label: d }))} value={(c.weekdays || []).map(String)} onChange={(v) => setCond("weekdays", v.map(Number))} />
      </label>
      <div className="fields">
        <TriState label="Commute" value={c.commute} onChange={(v) => setCond("commute", v)} />
        <TriState label="Indoor / trainer" value={c.trainer} onChange={(v) => setCond("trainer", v)} />
        <TriState label="Has heart rate" value={c.has_heartrate} onChange={(v) => setCond("has_heartrate", v)} />
        <TriState label="Has power" value={c.has_power} onChange={(v) => setCond("has_power", v)} />
      </div>

      <div className="section-label">Then</div>
      <div><Seg value={a.skip ? "skip" : "sync"} options={[{ value: "sync", label: `Copy to ${toKomoot ? "Komoot" : "Strava"}` }, { value: "skip", label: "Don't sync" }]}
        onChange={(v) => setA(v === "skip" ? { skip: true } : { ...a, skip: undefined })} /></div>
      {!a.skip && (
        <>
          <div className="fields">
            <label className="field">Title template<input value={a.name ?? ""} onChange={(e) => setA({ ...a, name: e.target.value || undefined })} placeholder="{name}" /></label>
            <label className="field">{toKomoot ? "Komoot sport" : "Strava sport type"}
              <select value={a.sport ?? ""} onChange={(e) => setA({ ...a, sport: e.target.value || undefined })}>
                <option value="">Map automatically</option>
                {(toKomoot ? meta?.komoot : meta?.strava)?.map((s) => <option key={s.key} value={s.key}>{s.label} ({s.key})</option>)}
              </select>
            </label>
          </div>
          <label className="field">Description template (replaces)<input value={a.description ?? ""} onChange={(e) => setA({ ...a, description: e.target.value || undefined })} /></label>
          <label className="field">Append to description<input value={a.append_description ?? ""} onChange={(e) => setA({ ...a, append_description: e.target.value || undefined })} placeholder="Synced from Komoot" /></label>
          <p className="small muted" style={{ margin: 0 }}>Template fields: <span className="mono">{TEMPLATE_HELP}</span></p>
          {toKomoot ? (
            <label className="field" style={{ maxWidth: 240 }}>Komoot visibility
              <select value={a.komoot?.visibility ?? ""} onChange={(e) => setA({ ...a, komoot: { visibility: e.target.value || undefined } })}>
                <option value="">Direction default</option><option value="private">Private</option><option value="friends">Friends</option><option value="public">Public</option>
              </select>
            </label>
          ) : (
            <div className="fields">
              <TriState label="Mute in followers' feeds" value={a.strava?.hide_from_home} onChange={(v) => setA({ ...a, strava: { ...(a.strava || {}), hide_from_home: v } })} />
              <TriState label="Mark as commute" value={a.strava?.commute} onChange={(v) => setA({ ...a, strava: { ...(a.strava || {}), commute: v } })} />
              <label className="field">Gear id<input value={a.strava?.gear_id ?? ""} onChange={(e) => setA({ ...a, strava: { ...(a.strava || {}), gear_id: e.target.value || undefined } })} placeholder="b1234567" /></label>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}


function Preview({ direction, onClose }: { direction: string; onClose: () => void }) {
  const { data: prefs } = usePrefs();
  const off = prefs && !prefs.sync[direction as "strava_to_komoot" | "komoot_to_strava"].enabled;
  const { data } = useQuery<any[]>({ queryKey: ["preview", direction], queryFn: () => api("/sync/preview", { params: { direction, limit: 100 } }) });
  const d = DIRS.find((x) => x.key === direction)!;
  return (
    <Modal title={<>Preview · {dirTitle(d)}</>} onClose={onClose}>
      <p className="small muted">What the current rules would do with your 100 most recent activities. Nothing is changed.</p>
      {off && <Callout kind="warn">This direction is switched off — nothing is copied automatically until you turn it on.</Callout>}
      {!data ? <Skeleton h={300} /> : (
        <div className="list">
          {data.map((p) => (
            <Link key={p.activity_id} to={`/activities/${p.activity_id}`} className="item">
              <span className={`badge ${p.would_sync ? "good" : ""}`}>{p.would_sync ? <IconCheck size={13} /> : <IconX size={13} />}{p.would_sync ? "copy" : "no"}</span>
              <div className="main-col">
                <span className="name ellipsis small">{p.name}</span>
                <span className="meta">{activityDate(p, false)} · {km(p.distance_m)} km · {p.blocked_by ?? p.reason}{p.would_sync && p.plan.name !== p.name ? ` · as “${p.plan.name}”` : ""}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </Modal>
  );
}

function DirectionCard({ dir, rules }: { dir: (typeof DIRS)[number]; rules: Rule[] }) {
  const { data: prefs } = usePrefs();
  const savePrefs = useSavePrefs();
  const [editing, setEditing] = useState<Partial<Rule> | null | undefined>(undefined);
  const [preview, setPreview] = useState(false);
  const qc = useQueryClient();
  const reorder = useMut(() => "/rules/reorder");
  const update = useMut((v) => `/rules/${v.id}`, "PUT");
  const del = useMut((v) => `/rules/${v.id}`, "DELETE");
  if (!prefs) return <Skeleton h={200} />;
  const p = prefs.sync[dir.key];
  const mine = rules.filter((r) => r.direction === dir.key);
  const move = (i: number, d: number) => {
    const ids = mine.map((r) => r.id);
    [ids[i], ids[i + d]] = [ids[i + d], ids[i]];
    reorder.mutate({ body: { ids } }, { onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }) });
  };
  const patch = (v: Record<string, any>) => savePrefs.mutate({ sync: { [dir.key]: v } });
  return (
    <Card title={dirTitle(dir)} hint={`New ${providerName(dir.from)} activities are copied to ${providerName(dir.to)}`}
      actions={<Switch checked={p.enabled} onChange={(v) => patch({ enabled: v })} label={p.enabled ? "On" : "Off"} />}>
      <div className="stack">
        <div className="stack" style={{ gap: 6 }}>
          <span className="small secondary">When no rule matches</span>
          <Seg block value={p.default_action} options={[{ value: "sync", label: "Copy it" }, { value: "skip", label: "Leave it" }]} onChange={(v) => patch({ default_action: v })} />
        </div>
        {dir.key === "strava_to_komoot" ? (
          <div className="stack" style={{ gap: 6 }}>
            <span className="small secondary">Visibility of copies on Komoot</span>
            <Seg block value={p.defaults?.komoot?.visibility ?? "private"} options={[{ value: "private", label: "Private" }, { value: "friends", label: "Friends" }, { value: "public", label: "Public" }]}
              onChange={(v) => patch({ defaults: { ...p.defaults, komoot: { visibility: v } } })} />
          </div>
        ) : (
          <Switch checked={!!p.defaults?.strava?.hide_from_home} onChange={(v) => patch({ defaults: { ...p.defaults, strava: { ...(p.defaults?.strava || {}), hide_from_home: v } } })}
            label={<span className="small">Hide copies from followers' feeds</span>} />
        )}
        <div className="row between mt8">
          <span className="section-label">Rules · first match wins</span>
          <div className="row">
            <button className="sm" onClick={() => setPreview(true)}>Preview</button>
            <button className="sm" onClick={() => setEditing(null)}><IconPlus size={16} />Rule</button>
          </div>
        </div>
        {mine.length === 0 ? <p className="small muted">No rules — every eligible activity follows the setting above.</p> : (
          <div className="stack" style={{ gap: 8 }}>
            {mine.map((r, i) => (
              <div key={r.id} style={{ border: "1px solid var(--border)", borderRadius: 12, padding: "10px 12px", opacity: r.enabled ? 1 : 0.55 }}>
                <div className="row between nowrap">
                  <button className="ghost" style={{ minHeight: 0, padding: 0, fontWeight: 650, justifyContent: "flex-start" }} onClick={() => setEditing(r)}>
                    <span className="badge">{i + 1}</span>&nbsp;<span className="ellipsis">{r.name}</span>
                  </button>
                  <Switch checked={r.enabled} onChange={(v) => update.mutate({ id: r.id, body: { enabled: v } })} />
                </div>
                <div className="xs muted" style={{ marginTop: 4 }}>{summarize(r)}</div>
                <div className="row between" style={{ marginTop: 6 }}>
                  <span className="xs muted">{r.actions?.skip ? <span className="badge warn">leave</span> : <span className="badge good">copy</span>} {r.match_count} matches{r.last_matched_at && ` · ${ago(r.last_matched_at)}`}</span>
                  <div className="row nowrap" style={{ gap: 2 }}>
                    <button className="sm ghost icon" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Higher priority"><IconArrowUp size={16} /></button>
                    <button className="sm ghost icon" disabled={i === mine.length - 1} onClick={() => move(i, 1)} aria-label="Lower priority"><IconArrowDown size={16} /></button>
                    <button className="sm ghost icon danger" onClick={() => confirm(`Delete rule “${r.name}”?`) && del.mutate({ id: r.id })} aria-label="Delete"><IconTrash size={16} /></button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      {editing !== undefined && <RuleEditor rule={editing} direction={dir.key} onClose={() => setEditing(undefined)} />}
      {preview && <Preview direction={dir.key} onClose={() => setPreview(false)} />}
    </Card>
  );
}

function FullHistory({ ready }: { ready: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [dirs, setDirs] = useState<string[]>(["komoot_to_strava", "strava_to_komoot"]);
  const [applyRules, setApplyRules] = useState(true);
  const { data: st } = useQuery<any>({
    queryKey: ["fullsync"],
    queryFn: () => api("/sync/full-history"),
    refetchInterval: (q) => (["importing", "running"].includes(q.state.data?.phase) ? 4000 : false),
  });
  const call = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => api(path, { method: "POST", body }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["fullsync"] }); qc.invalidateQueries({ queryKey: ["jobs"] }); },
    onError: (e: Error) => toast(e.message, true),
  });
  const phase: string = st?.phase ?? "idle";
  const prog = st?.progress;
  const total = prog ? prog.done + prog.failed + prog.queued + prog.running : 0;
  return (
    <Card title="Bring everything up to date" icon={IconImport}
      hint="Once: import the complete history of both platforms, merge duplicates, copy whatever is missing on either side">
      {!ready ? <Callout kind="warn">Connect both Strava and Komoot first.</Callout> : (
        <div className="stack">
          {(phase === "idle" || phase === "finished" || phase === "error") && (
            <>
              {phase === "finished" && <Callout kind="good">Done{st.finished_at ? ` ${ago(st.finished_at)}` : ""}. Both platforms are up to date — new activities follow your direction settings.</Callout>}
              {phase === "error" && <Callout kind="bad">The import failed: {st.error}</Callout>}
              <div className="stack" style={{ gap: 6 }}>
                <span className="small secondary">Copy missing activities</span>
                {DIRS.map((d) => (
                  <label key={d.key} className="row nowrap" style={{ cursor: "pointer" }}>
                    <input type="checkbox" checked={dirs.includes(d.key)} onChange={(e) => setDirs(e.target.checked ? [...dirs, d.key] : dirs.filter((x) => x !== d.key))} />
                    {dirTitle(d)}
                  </label>
                ))}
              </div>
              <Switch checked={applyRules} onChange={setApplyRules} label={<span className="small">Respect my rules (skip what they skip)</span>} />
              <button className="primary" disabled={!dirs.length || call.isPending} onClick={() => call.mutate({ path: "/sync/full-history/analyse", body: { directions: dirs, apply_rules: applyRules } })}>
                <IconImport size={18} />Analyse all-time history
              </button>
              <p className="xs muted">Nothing is uploaded yet — you will see exactly what would be copied first.</p>
            </>
          )}
          {phase === "importing" && (
            <Callout><b>Reading your complete history…</b> Strava and Komoot are imported and matched. This takes a minute or two for large histories.</Callout>
          )}
          {phase === "ready" && st.preview && (
            <>
              <Callout kind="good">{int(st.counts.activities)} activities in total · {int(st.counts.merged)} newly merged duplicates</Callout>
              {Object.entries(st.preview as Record<string, any>).map(([k, v]) => {
                const d = DIRS.find((x) => x.key === k)!;
                const cannot = Object.entries(v.cannot_copy as Record<string, number>);
                return (
                  <div key={k} style={{ border: "1px solid var(--border)", borderRadius: 12, padding: 12 }}>
                    <div className="row between">{dirTitle(d)}<span className="big-num" style={{ fontSize: 22 }}>{int(v.to_copy)}</span></div>
                    <div className="xs muted" style={{ marginTop: 4 }}>
                      to copy{v.skipped_by_rules ? ` · ${v.skipped_by_rules} left out by your rules` : ""}
                      {cannot.map(([r, n]) => ` · ${n} ${r}`).join("")}
                    </div>
                  </div>
                );
              })}
              <div className="row">
                <button className="primary grow" disabled={call.isPending} onClick={() => call.mutate({ path: "/sync/full-history/start" }, { onSuccess: () => toast("Copying started — it continues in the background") })}>
                  <IconPlay size={18} />Start copying
                </button>
                <button onClick={() => call.mutate({ path: "/sync/full-history/cancel" })}>Cancel</button>
              </div>
              <p className="xs muted">Copies run in the background within Strava's rate limits (roughly 30–40 per 15 minutes); large histories take a few hours. You can close this page.</p>
            </>
          )}
          {phase === "running" && prog && (
            <>
              <div className="row between small"><span><b>{int(prog.done)}</b> of {int(total)} copied{prog.failed ? ` · ${prog.failed} failed` : ""}</span><span className="muted">{total ? Math.round(((prog.done + prog.failed) / total) * 100) : 0}%</span></div>
              <div className="progress">
                <span style={{ width: `${total ? (prog.done / total) * 100 : 0}%`, background: "var(--good)" }} />
                <span style={{ width: `${total ? (prog.failed / total) * 100 : 0}%`, background: "var(--bad)" }} />
              </div>
              <div className="row">
                <Link to="/sync#jobs" className="small">See the queue</Link>
                <button className="sm ghost danger" onClick={() => confirm("Stop copying? Copies already made stay.") && call.mutate({ path: "/sync/full-history/cancel" })}>Stop</button>
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

function Jobs() {
  const [status, setStatus] = useState("queued,running,failed");
  const { data } = useQuery<{ items: SyncJob[]; total: number }>({ queryKey: ["jobs", status], queryFn: () => api("/sync/jobs", { params: { status: status === "all" ? undefined : status, limit: 100 } }), refetchInterval: 15000 });
  const retry = useMut((v) => `/sync/jobs/${v.id}/retry`);
  const remove = useMut((v) => `/sync/jobs/${v.id}`, "DELETE");
  return (
    <Card title="Copies" icon={IconList} flush id="jobs" hint={data ? `${int(data.total)} ${status === "all" ? "in total" : "shown"}` : undefined}
      actions={<Seg value={status} options={[{ value: "queued,running,failed", label: "Open" }, { value: "done", label: "Done" }, { value: "skipped", label: "Left out" }, { value: "all", label: "All" }]} onChange={setStatus} />}>
      {!data ? <div style={{ padding: 14 }}><Skeleton h={160} /></div> : !data.items.length ? <Empty title="Nothing here" icon={IconCheck} /> : (
        <div className="list" style={{ maxHeight: 560, overflowY: "auto" }}>
          {data.items.map((j) => (
            <div key={j.id} className="item" style={{ cursor: "default", alignItems: "flex-start" }}>
              <span className="row nowrap" style={{ gap: 3, marginTop: 2 }}><BrandIcon provider={j.source_provider} size={16} /><IconRight size={13} /><BrandIcon provider={j.target_provider} size={16} /></span>
              <div className="main-col">
                <Link to={`/activities/${j.activity_id}`} className="name ellipsis small">{j.plan?.name || j.activity?.name}</Link>
                <span className="meta">{j.activity && `${activityDate(j.activity, false)} · ${km(j.activity.distance_m)} km · `}{j.reason}</span>
                {j.error && <span className="xs" style={{ color: "var(--bad)" }}>{j.error.slice(0, 160)}</span>}
                {j.next_attempt_at && j.status === "queued" && <span className="xs muted">next try {dateTime(j.next_attempt_at)}</span>}
              </div>
              <div className="side">
                <StatusBadge status={j.status} />
                <div className="row nowrap" style={{ gap: 2 }}>
                  {j.target_url && <a href={j.target_url} target="_blank" rel="noreferrer" className="xs">open</a>}
                  {(j.status === "failed" || j.status === "skipped") && <button className="sm ghost icon" onClick={() => retry.mutate({ id: j.id })} aria-label={j.status === "skipped" ? "Check again" : "Retry"}><IconRefresh size={16} /></button>}
                  {j.status !== "done" && j.status !== "running" && <button className="sm ghost icon" onClick={() => remove.mutate({ id: j.id })} aria-label="Remove"><IconTrash size={16} /></button>}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function Runs() {
  const { data } = useQuery<SyncRun[]>({ queryKey: ["runs"], queryFn: () => api("/sync/runs", { params: { limit: 10 } }), refetchInterval: 15000 });
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Card title="Recent sync runs" icon={IconHistory} flush>
      {!data?.length ? <Empty title="No runs yet" /> : (
        <div className="list">
          {data.map((r) => (
            <div key={r.id} className="item" onClick={() => setOpen(open === r.id ? null : r.id)} style={{ alignItems: "flex-start" }}>
              <StatusBadge status={r.status} />
              <div className="main-col">
                <span className="small">{dateTime(r.started_at)} <span className="muted">· {r.trigger}</span></span>
                {open === r.id && <pre className="mono" style={{ whiteSpace: "pre-wrap", margin: "6px 0 0" }}>{r.log.join("\n")}</pre>}
              </div>
              <span className="xs muted">{r.finished_at ? `${Math.round((new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000)} s` : "running"}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export default function SyncPage() {
  const { data: rules } = useQuery<Rule[]>({ queryKey: ["rules"], queryFn: () => api("/rules") });
  const { data: prefs } = usePrefs();
  const savePrefs = useSavePrefs();
  const { data: status } = useStatus();
  const run = useRunSync();
  const reeval = useMut(() => "/sync/reevaluate");
  const toast = useToast();
  const ready = !!(status?.connections.strava.connected && status?.connections.komoot.connected);
  const cov = status?.coverage;
  const jobs = status?.jobs ?? {};
  return (
    <>
      <div className="page-head">
        <div><h1>Sync</h1><div className="sub">An activity that already exists on the other platform is never copied again.</div></div>
        <button className="primary sm" onClick={() => run.mutate(false)} disabled={status?.running}><IconRefresh size={16} className={status?.running ? "spin" : ""} />{status?.running ? "Running…" : "Sync now"}</button>
      </div>
      {status && !ready && <div style={{ marginBottom: 16 }}><Callout kind="warn">Both Strava and Komoot must be connected to sync. <Link to="/settings">Connect in Settings</Link></Callout></div>}

      <div className="stack gap16">
        {cov && (
          <Card>
            <div className="flow">
              <div className="side"><BrandIcon provider="strava" size={30} /><b>{int(cov.provider_records.strava ?? 0)}</b><span className="xs muted">{int(cov.strava_only)} only here</span></div>
              <div className="mid"><IconSync size={26} /><b style={{ color: "var(--text-primary)" }}>{int(cov.both)}</b>on both</div>
              <div className="side"><BrandIcon provider="komoot" size={30} /><b>{int(cov.provider_records.komoot ?? 0)}</b><span className="xs muted">{int(cov.komoot_only)} only here</span></div>
            </div>
            <div className="row mt16" style={{ justifyContent: "center", gap: 6 }}>
              {(jobs.queued ?? 0) > 0 && <span className="badge info">{jobs.queued} waiting</span>}
              {(jobs.failed ?? 0) > 0 && <span className="badge bad"><IconWarn size={13} />{jobs.failed} failed</span>}
              {(jobs.done ?? 0) > 0 && <span className="badge good">{jobs.done} copied</span>}
              {status?.last_run && <span className="badge">last run {ago(status.last_run.started_at)}</span>}
            </div>
          </Card>
        )}

        <FullHistory ready={ready} />

        <div className="grid g2">
          {rules ? DIRS.map((d) => <DirectionCard key={d.key} dir={d} rules={rules} />) : <><Skeleton h={300} /><Skeleton h={300} /></>}
        </div>

        <Card title="Safety" icon={IconSettings} hint="Applies to automatic sync">
          {prefs && (
            <div className="stack">
              <div className="fields">
                <label className="field">Only copy activities from
                  <input type="date" value={prefs.sync.start_date ?? ""} onChange={(e) => savePrefs.mutate({ sync: { start_date: e.target.value || null } })} />
                </label>
                <label className="field">Wait before copying (min)
                  <input type="number" inputMode="numeric" min={0} defaultValue={prefs.sync.delay_minutes} onBlur={(e) => savePrefs.mutate({ sync: { delay_minutes: Number(e.target.value) } })} />
                </label>
              </div>
              <Switch checked={prefs.sync.auto} onChange={(v) => savePrefs.mutate({ sync: { auto: v } })} label={<span className="small">Copy automatically after every sync</span>} />
              <p className="xs muted">The wait lets devices that upload to both platforms arrive first, so they are merged instead of copied. Older activities are only copied by hand or with “Bring everything up to date”.</p>
              <div><button className="sm" onClick={() => reeval.mutate(undefined, { onSuccess: (r: any) => toast(`Rules re-applied: ${r.queued} to copy, ${r.skipped} left out`) })}>Re-apply rules to left-out activities</button></div>
            </div>
          )}
        </Card>

        <Jobs />
        <Runs />
      </div>
    </>
  );
}
