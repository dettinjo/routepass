import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ICON,
  BrandIcon, IconArrowDown, IconArrowUp, IconCheck, IconHistory, IconImport, IconList, IconPlay, IconPlus,
  IconRefresh, IconRight, IconSettings, IconSync, IconTrash, IconWarn, IconX, providerName,
} from "../components/icons";
import { Callout, Card, Empty, InfoTip, Menu, Modal, Seg, Skeleton, StatusBadge, Switch, useToast } from "../components/ui";
import { presetsFor, RuleEditor, RuleSentence, type Preset } from "../components/RuleEditor";
import { api } from "../lib/api";
import { activityDate, ago, dateTime, int, km } from "../lib/format";
import { usePrefs, useRunSync, useSavePrefs, useSportMeta, useStatus } from "../lib/hooks";
import type { Rule, SyncJob, SyncRun } from "../lib/types";

const DIRS = [
  { key: "komoot_to_strava", from: "komoot", to: "strava" },
  { key: "strava_to_komoot", from: "strava", to: "komoot" },
] as const;
const dirTitle = (d: { from: string; to: string }) => (
  <span className="row nowrap" style={{ gap: 6 }}><BrandIcon provider={d.from} size={18} />{providerName(d.from)}<IconRight size={ICON.button} /><BrandIcon provider={d.to} size={18} />{providerName(d.to)}</span>
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
              <span className={`badge ${p.would_sync ? "good" : ""}`}>{p.would_sync ? <IconCheck size={ICON.inline} /> : <IconX size={ICON.inline} />}{p.would_sync ? "copy" : "no"}</span>
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
  const [preset, setPreset] = useState<Preset | null>(null);
  const { data: meta } = useSportMeta();
  const sportLabel = (k: string) => meta?.strava.find((x) => x.key === k)?.label ?? k;
  const create = useMut(() => "/rules");
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
        <Switch checked={p.match_visibility ?? true} onChange={(v) => patch({ match_visibility: v })}
          label={<span className="small">Copies get the same visibility as the original, and follow when you change it</span>} />
        {dir.key === "strava_to_komoot" ? (
          <div className="stack" style={{ gap: 6 }}>
            <span className="small secondary">{(p.match_visibility ?? true) ? "Visibility on Komoot when the Strava original's is unknown" : "Visibility of copies on Komoot"}</span>
            <Seg block value={p.defaults?.komoot?.visibility ?? "private"} options={[{ value: "private", label: "Private" }, { value: "friends", label: "Friends" }, { value: "public", label: "Public" }]}
              onChange={(v) => patch({ defaults: { ...p.defaults, komoot: { visibility: v } } })} />
          </div>
        ) : (
          <div className="stack" style={{ gap: 8 }}>
            <Switch checked={!!p.defaults?.strava?.hide_from_home} onChange={(v) => patch({ defaults: { ...p.defaults, strava: { ...(p.defaults?.strava || {}), hide_from_home: v } } })}
              label={<span className="small">Hide copies from followers' feeds</span>} />
            <Switch checked={p.sync_photos ?? true} onChange={(v) => patch({ sync_photos: v })}
              label={<span className="small">Copy tour photos to Strava (uses Strava Web Session)</span>} />
          </div>
        )}
        <div className="row between mt8">
          <span className="section-label row nowrap" style={{ gap: 4 }}>Rules<InfoTip>Rules are checked from top to bottom; the first one that matches decides. Activities no rule matches follow “When no rule matches”.</InfoTip></span>
          <div className="row nowrap">
            <button className="sm ghost" onClick={() => setPreview(true)}><IconList size={ICON.button} />Preview</button>
            <button className="sm" onClick={() => { setPreset(null); setEditing(null); }}><IconPlus size={ICON.button} />Add rule</button>
          </div>
        </div>
        {mine.length === 0 ? (
          <div className="stack" style={{ gap: 8 }}>
            <p className="small muted">No rules yet — every activity follows the setting above. Common rules:</p>
            <div className="chips" style={{ flexWrap: "wrap" }}>
              {presetsFor(dir.key, prefs.places ?? []).slice(0, 4).map((pr) => (
                <button key={pr.id} className="chip" onClick={() => { setPreset(pr); setEditing(null); }}><pr.icon size={ICON.button} />{pr.label}</button>
              ))}
            </div>
          </div>
        ) : (
          <ol className="rule-list">
            {mine.map((r, i) => (
              <li key={r.id} className={r.enabled ? "" : "off"}>
                <span className="rule-num">{i + 1}</span>
                <button className="rule-main" onClick={() => { setPreset(null); setEditing(r); }} aria-label={`Edit rule ${r.name}`}>
                  <b className="ellipsis">{r.name}</b>
                  <RuleSentence rule={r} target={dir.to} sportLabel={sportLabel} />
                  <span className="xs muted">{r.match_count ? `${r.match_count} matched${r.last_matched_at ? `, last ${ago(r.last_matched_at)}` : ""}` : "Not matched yet"}{!r.enabled && " · paused"}</span>
                </button>
                <div className="row nowrap" style={{ gap: 2 }}>
                  <Switch checked={r.enabled} onChange={(v) => update.mutate({ id: r.id, body: { enabled: v } })} />
                  <Menu label={`Actions for ${r.name}`}>
                    <button onClick={() => { setPreset(null); setEditing(r); }}><IconSettings size={ICON.button} />Edit</button>
                    <button onClick={() => create.mutate({ body: { name: `${r.name} (copy)`, direction: r.direction, enabled: false, conditions: r.conditions, actions: r.actions, priority: 1000 } })}><IconPlus size={ICON.button} />Duplicate</button>
                    <button disabled={i === 0} onClick={() => move(i, -1)}><IconArrowUp size={ICON.button} />Move up</button>
                    <button disabled={i === mine.length - 1} onClick={() => move(i, 1)}><IconArrowDown size={ICON.button} />Move down</button>
                    <div className="sep" />
                    <button className="danger" onClick={() => confirm(`Delete rule “${r.name}”?`) && del.mutate({ id: r.id })}><IconTrash size={ICON.button} />Delete</button>
                  </Menu>
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
      {editing !== undefined && <RuleEditor rule={editing} preset={preset} direction={dir.key} onClose={() => { setEditing(undefined); setPreset(null); }} />}
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
                <IconImport size={ICON.header} />Analyse all-time history
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
                  <IconPlay size={ICON.header} />Start copying
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
                <span style={{ width: `${total ? (prog.done / total) * 100 : 0}%`, background: "var(--text-secondary)" }} />
                <span style={{ width: `${total ? (prog.failed / total) * 100 : 0}%`, background: "var(--bad)" }} />
              </div>
              <div className="row">
                <Link to="/sync#jobs" className="small">See the queue</Link>
                <button className="sm ghost danger" onClick={() => confirm("Stop copying? Copies already made stay.") && call.mutate({ path: "/sync/full-history/cancel" })}><IconX size={ICON.button} />Stop</button>
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

function Duplicates() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery<any[]>({ queryKey: ["duplicates"], queryFn: () => api("/activities/duplicates") });
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body: unknown }) => api(path, { method: "POST", body }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["duplicates"] }); qc.invalidateQueries({ queryKey: ["activities"] }); qc.invalidateQueries({ queryKey: ["status"] }); },
    onError: (e: Error) => toast(e.message, true),
  });
  if (!data?.length) return null;
  return (
    <Card title="Possible duplicates" icon={IconSync} hint="Looked alike but were not merged automatically — check and decide" flush>
      <div className="list">
        {data.map((d) => (
          <div key={`${d.activity.id}-${d.candidate.id}`} className="item" style={{ cursor: "default", flexWrap: "wrap" }}>
            <div className="main-col" style={{ minWidth: 220 }}>
              {[d.activity, d.candidate].map((a: any) => (
                <Link key={a.id} to={`/activities/${a.id}`} className="row nowrap small" style={{ gap: 6 }}>
                  {a.providers.map((p: string) => <BrandIcon key={p} provider={p} size={14} />)}
                  <span className="ellipsis">{a.name}</span>
                  <span className="muted" style={{ flex: "none" }}>· {km(a.distance_m)} km · {activityDate(a)}</span>
                </Link>
              ))}
              <span className="xs muted">{d.time_diff_min} min apart{d.distance_diff_pct != null ? ` · ${d.distance_diff_pct} % distance difference` : ""}</span>
            </div>
            <div className="row nowrap">
              <button className="sm primary" onClick={() => act.mutate({ path: `/activities/${d.activity.id}/merge`, body: { other_id: d.candidate.id } }, { onSuccess: () => toast("Merged into one activity") })}><IconCheck size={ICON.button} />Same — merge</button>
              <button className="sm ghost" onClick={() => act.mutate({ path: `/activities/${d.activity.id}/dismiss-duplicate`, body: { other_id: d.candidate.id } })}><IconX size={ICON.button} />Not the same</button>
            </div>
          </div>
        ))}
      </div>
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
              <span className="row nowrap" style={{ gap: 3, marginTop: 2 }}><BrandIcon provider={j.source_provider} size={16} /><IconRight size={ICON.inline} /><BrandIcon provider={j.target_provider} size={16} /></span>
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
                  {(j.status === "failed" || j.status === "skipped") && <button className="sm ghost icon" onClick={() => retry.mutate({ id: j.id })} aria-label={j.status === "skipped" ? "Check again" : "Retry"}><IconRefresh size={ICON.button} /></button>}
                  {j.status !== "done" && j.status !== "running" && <button className="sm ghost icon" onClick={() => remove.mutate({ id: j.id })} aria-label="Remove"><IconTrash size={ICON.button} /></button>}
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
        <div><h1>Sync</h1><div className="sub static">An activity that already exists on the other platform is never copied again.</div></div>
        <button className="primary sm" onClick={() => run.mutate(false)} disabled={status?.running}><IconRefresh size={ICON.button} className={status?.running ? "spin" : ""} />{status?.running ? "Running…" : "Sync now"}</button>
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
              {(jobs.failed ?? 0) > 0 && <span className="badge bad"><IconWarn size={ICON.inline} />{jobs.failed} failed</span>}
              {(jobs.done ?? 0) > 0 && <span className="badge good">{jobs.done} copied</span>}
              {status?.last_run && <span className="badge">last run {ago(status.last_run.started_at)}</span>}
            </div>
          </Card>
        )}

        <FullHistory ready={ready} />

        <div className="grid g2">
          {rules ? DIRS.map((d) => <DirectionCard key={d.key} dir={d} rules={rules} />) : <><Skeleton h={300} /><Skeleton h={300} /></>}
        </div>

        <Card title="Safety & timing" icon={IconSettings} hint="Applies to automatic sync">
          {prefs && (
            <div className="stack">
              <div className="fields">
                <label className="field">Only copy activities from
                  <input type="date" value={prefs.sync.start_date ?? ""} onChange={(e) => savePrefs.mutate({ sync: { start_date: e.target.value || null } })} />
                </label>
                <label className="field">Wait before copying (min)
                  <input key={`delay-${prefs.sync.delay_minutes}`} type="number" inputMode="numeric" min={0} defaultValue={prefs.sync.delay_minutes} onBlur={(e) => savePrefs.mutate({ sync: { delay_minutes: Math.max(0, Number(e.target.value)) } })} />
                </label>
              </div>
              <Switch checked={prefs.sync.auto} onChange={(v) => savePrefs.mutate({ sync: { auto: v } })} label={<span className="small">Copy automatically after every sync</span>} />
              <p className="xs muted">The wait lets devices that upload to both platforms arrive first, so they are merged instead of copied. If your device only uploads to one platform, a wait of 0 min copies on the next check. How often RoutePass checks is set in <Link to="/settings/sync">Settings → Sync & matching</Link> (every 30 min or manually; instantly with the Strava webhook).</p>
              <div className="row">
                <button className="sm" onClick={() => reeval.mutate(undefined, { onSuccess: (r: any) => toast(`Rules re-applied: ${r.queued} to copy, ${r.skipped} left out`) })}><IconRefresh size={ICON.button} />Re-apply rules to left-out activities</button>
              </div>
            </div>
          )}
        </Card>

        <Duplicates />
        <Jobs />
        <Runs />
      </div>
    </>
  );
}
