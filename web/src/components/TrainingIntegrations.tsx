import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { ago, int } from "../lib/format";
import { useDebouncedCallback } from "../lib/hooks";
import { ICON, IconBellRing, IconCalendarAdd, IconCopy2, IconKey, IconPlus, IconRefresh, IconRight, IconSparkles, IconTrash } from "./icons";
import { Callout, Card, Menu, SavedMark, StatusBadge, Switch, useToast } from "./ui";

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const out = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) out[i] = rawData.charCodeAt(i);
  return out;
}

type CalForm = { target: string; busy: string[]; tz: string; buffer: string; auto: boolean };

/** Settings save as you change them; credentials (secrets) keep an explicit Save button. */
export function GoogleCalendarCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: cfg } = useQuery<any>({ queryKey: ["gcal-config"], queryFn: () => api("/connections/google-calendar") });
  const { data: calendars, refetch: refetchCals } = useQuery<any[]>({
    queryKey: ["gcal-calendars"], queryFn: () => api("/connections/google-calendar/calendars"), enabled: Boolean(cfg?.connected),
  });
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [form, setForm] = useState<CalForm | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const g = params.get("gcal");
    if (!g) return;
    if (g === "connected") {
      toast("Google Calendar connected — choose your training calendar.");
      qc.invalidateQueries({ queryKey: ["gcal-config"] });
      qc.invalidateQueries({ queryKey: ["gcal-calendars"] });
    } else toast("Google Calendar authorization failed or was cancelled.", true);
    params.delete("gcal");
    window.history.replaceState({}, "", `${window.location.pathname}${params.toString() ? "?" + params : ""}`);
  }, [qc, toast]);

  useEffect(() => {
    if (!cfg || form) return;
    setForm({
      target: cfg.target_calendar_id || "", busy: cfg.busy_calendar_ids || [],
      tz: cfg.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Berlin",
      buffer: String(cfg.buffer_minutes ?? 20), auto: cfg.auto_sync ?? true,
    });
  }, [cfg, form]);

  const saveCfg = useMutation({
    mutationFn: (f: CalForm) => api("/connections/google-calendar/config", {
      method: "PUT",
      body: {
        target_calendar_id: f.target || null,
        target_calendar_name: calendars?.find((c) => c.id === f.target)?.summary || cfg?.target_calendar_name || null,
        busy_calendar_ids: f.busy, timezone: f.tz.trim() || "Europe/Berlin", buffer_minutes: Number(f.buffer) || 20, auto_sync: f.auto,
      },
    }),
    onSuccess: (res) => { qc.setQueryData(["gcal-config"], res); setSavedAt(Date.now()); },
    onError: (e: Error) => toast(e.message, true),
  });
  const debounced = useDebouncedCallback((f: CalForm) => saveCfg.mutate(f), 700);
  const update = (patch: Partial<CalForm>, now = true) => {
    if (!form) return;
    const next = { ...form, ...patch };
    setForm(next);
    if (now) saveCfg.mutate(next); else debounced(next);
  };

  const saveApp = useMutation({
    mutationFn: () => api("/connections/google-calendar/app", { method: "PUT", body: { client_id: clientId.trim(), client_secret: clientSecret.trim() } }),
    onSuccess: (res) => { qc.setQueryData(["gcal-config"], res); setClientId(""); setClientSecret(""); toast("Saved Google OAuth client"); },
    onError: (e: Error) => toast(e.message, true),
  });
  const createCal = useMutation({
    mutationFn: () => api<any>("/connections/google-calendar/calendars", { method: "POST", body: { name: "RoutePass Training" } }),
    onSuccess: (cal) => { refetchCals(); update({ target: cal.id }); toast(`Created “${cal.summary}”`); },
    onError: (e: Error) => toast(e.message, true),
  });
  const disconnect = useMutation({
    mutationFn: () => api("/connections/google-calendar", { method: "DELETE" }),
    onSuccess: (res) => { qc.setQueryData(["gcal-config"], res); setForm(null); toast("Disconnected Google Calendar"); },
    onError: (e: Error) => toast(e.message, true),
  });
  const connect = async () => {
    try { window.location.assign((await api<{ url: string }>("/connections/google-calendar/authorize")).url); } catch (e: any) { toast(e.message, true); }
  };

  return (
    <Card title="Google Calendar" icon={IconCalendarAdd} hint="Places sessions around busy times in your other calendars"
      actions={<div className="row nowrap"><SavedMark at={savedAt} />
        <StatusBadge status={cfg?.connected ? "completed" : "planned"} label={cfg?.connected ? "Connected" : "Not connected"} />
        {cfg?.connected && (
          <Menu>
            <button onClick={() => refetchCals()}><IconRefresh size={ICON.button} />Reload calendar list</button>
            <div className="sep" />
            <button className="danger" onClick={() => confirm("Disconnect Google Calendar?") && disconnect.mutate()}><IconTrash size={ICON.button} />Disconnect</button>
          </Menu>
        )}
      </div>}>
      <div className="stack">
        {!cfg?.connected ? (
          <>
            <p className="small secondary">RoutePass reads when you are busy and keeps a dedicated training calendar up to date when sessions move.</p>
            <div className="row">
              <button className="primary sm" disabled={!cfg?.oauth_configured} onClick={connect}><IconCalendarAdd size={ICON.button} />Connect Google Calendar</button>
              {!cfg?.oauth_configured && <span className="xs muted">Add the Google OAuth client below first.</span>}
            </div>
            <details className="more" open={!cfg?.oauth_configured}>
              <summary><IconRight size={ICON.button} />Google OAuth client</summary>
              <div className="stack mt8">
                {cfg?.redirect_uri && (
                  <div className="row xs muted">
                    <span>Authorized redirect URI: <span className="mono">{cfg.redirect_uri}</span></span>
                    <button className="sm ghost" onClick={() => { navigator.clipboard?.writeText(cfg.redirect_uri); toast("Copied"); }}><IconCopy2 size={ICON.button} />Copy</button>
                  </div>
                )}
                <div className="fields">
                  <label className="field">Client ID<input value={clientId} onChange={(e) => setClientId(e.target.value)} /></label>
                  <label className="field">Client secret<input type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} /></label>
                </div>
                <div><button className="sm" disabled={!clientId.trim() || !clientSecret.trim() || saveApp.isPending} onClick={() => saveApp.mutate()}><IconKey size={ICON.button} />Save client</button></div>
              </div>
            </details>
          </>
        ) : form && (
          <>
            <label className="field">Training calendar (sessions are written here)
              <div className="row nowrap">
                <select value={form.target} onChange={(e) => update({ target: e.target.value })}>
                  <option value="">Choose a calendar…</option>
                  {(calendars || []).filter((c) => c.access_role === "owner" || c.access_role === "writer").map((c) => (
                    <option key={c.id} value={c.id}>{c.summary}{c.primary ? " (primary)" : ""}</option>
                  ))}
                </select>
                <button className="sm" disabled={createCal.isPending} onClick={() => createCal.mutate()} title="Create a “RoutePass Training” calendar"><IconPlus size={ICON.button} />New</button>
              </div>
            </label>
            {calendars && calendars.length > 0 && (
              <div className="stack" style={{ gap: 6 }}>
                <span className="small secondary" style={{ fontWeight: 600 }}>Avoid times that are busy in</span>
                <div className="row">
                  {calendars.filter((c) => c.id !== form.target).map((c) => (
                    <label key={c.id} className="check-chip">
                      <input type="checkbox" checked={form.busy.includes(c.id)} onChange={() => update({ busy: form.busy.includes(c.id) ? form.busy.filter((x) => x !== c.id) : [...form.busy, c.id] })} />
                      {c.summary}
                    </label>
                  ))}
                </div>
              </div>
            )}
            <div className="fields">
              <label className="field">Time zone<input value={form.tz} onChange={(e) => update({ tz: e.target.value }, false)} /></label>
              <label className="field">Gap around meetings (min)<input type="number" min="0" max="120" value={form.buffer} onChange={(e) => update({ buffer: e.target.value }, false)} /></label>
            </div>
            <Switch checked={form.auto} onChange={(v) => update({ auto: v })} label="Move calendar events automatically when the plan changes" />
          </>
        )}
      </div>
    </Card>
  );
}

const hourToTime = (h: number) => `${String(h).padStart(2, "0")}:00`;
const timeToHour = (t: string) => Number(t.split(":")[0] || 0);
type PushForm = { lead: string; adapted: boolean; completed: boolean; qs: number; qe: number };

export function PushNotificationsCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: cfg } = useQuery<any>({ queryKey: ["push-config"], queryFn: () => api("/push/config") });
  const [supported] = useState(() => typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window);
  const [subscribing, setSubscribing] = useState(false);
  const [form, setForm] = useState<PushForm | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    if (!cfg || form) return;
    setForm({ lead: String(cfg.reminder_minutes_before ?? 60), adapted: cfg.notify_adapted ?? true, completed: cfg.notify_completed ?? true, qs: cfg.quiet_start_hour ?? 22, qe: cfg.quiet_end_hour ?? 7 });
  }, [cfg, form]);

  const saveCfg = useMutation({
    mutationFn: (f: PushForm) => api("/push/config", {
      method: "PUT",
      body: {
        reminder_minutes_before: Number(f.lead) || 60, notify_adapted: f.adapted, notify_completed: f.completed,
        quiet_start_hour: f.qs, quiet_end_hour: f.qe, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Berlin",
      },
    }),
    onSuccess: (res) => { qc.setQueryData(["push-config"], res); setSavedAt(Date.now()); },
    onError: (e: Error) => toast(e.message, true),
  });
  const debounced = useDebouncedCallback((f: PushForm) => saveCfg.mutate(f), 700);
  const update = (patch: Partial<PushForm>, now = true) => {
    if (!form) return;
    const next = { ...form, ...patch };
    setForm(next);
    if (now) saveCfg.mutate(next); else debounced(next);
  };
  const testPush = useMutation({
    mutationFn: () => api<any>("/push/test", { method: "POST" }),
    onSuccess: (r) => (r.sent > 0 ? toast("Test notification sent") : toast("No device is subscribed yet", true)),
    onError: (e: Error) => toast(e.message, true),
  });

  const enablePush = async () => {
    if (!supported || !cfg?.vapid_public_key) return;
    setSubscribing(true);
    try {
      if ((await Notification.requestPermission()) !== "granted") { toast("Notifications are blocked for this site", true); return; }
      const reg = await navigator.serviceWorker.ready;
      const sub = (await reg.pushManager.getSubscription()) || (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(cfg.vapid_public_key) as BufferSource }));
      const json = sub.toJSON();
      qc.setQueryData(["push-config"], await api("/push/subscribe", { method: "POST", body: { endpoint: json.endpoint, keys: json.keys } }));
      toast("Notifications enabled on this device");
    } catch (e: any) {
      toast(e.message || "Could not enable notifications", true);
    } finally {
      setSubscribing(false);
    }
  };

  return (
    <Card title="Reminders & notifications" icon={IconBellRing} hint="Before each session, and when the plan changes"
      actions={<div className="row nowrap"><SavedMark at={savedAt} /><StatusBadge status={cfg?.subscriptions > 0 ? "completed" : "planned"} label={cfg?.subscriptions > 0 ? `${cfg.subscriptions} device${cfg.subscriptions > 1 ? "s" : ""}` : "Off"} /></div>}>
      <div className="stack">
        {!supported && <Callout kind="info">This browser cannot receive notifications. On iPhone, add RoutePass to the Home Screen first.</Callout>}
        <div className="row">
          <button className="sm primary" disabled={!supported || subscribing} onClick={enablePush}><IconBellRing size={ICON.button} />{subscribing ? "Enabling…" : "Enable on this device"}</button>
          <button className="sm" disabled={!cfg?.subscriptions || testPush.isPending} onClick={() => testPush.mutate()}>Send a test</button>
        </div>
        {form && (
          <>
            <div className="fields">
              <label className="field">Remind me before a session (min)<input type="number" min="5" max="1440" value={form.lead} onChange={(e) => update({ lead: e.target.value }, false)} /></label>
              <label className="field">Quiet from<input type="time" step={3600} value={hourToTime(form.qs)} onChange={(e) => update({ qs: timeToHour(e.target.value) })} /></label>
              <label className="field">Quiet until<input type="time" step={3600} value={hourToTime(form.qe)} onChange={(e) => update({ qe: timeToHour(e.target.value) })} /></label>
            </div>
            <Switch checked={form.adapted} onChange={(v) => update({ adapted: v })} label="When the plan is adapted or a session moves" />
            <Switch checked={form.completed} onChange={(v) => update({ completed: v })} label="When a recorded activity completes a session" />
          </>
        )}
      </div>
    </Card>
  );
}

/** Gemini key, budget and models. The key is a secret, so it has its own Save. */
export function AICoachCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery<any>({ queryKey: ["training-ai-config"], queryFn: () => api("/training/ai-config") });
  const [apiKey, setApiKey] = useState("");
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [budget, setBudget] = useState<string | null>(null);
  const models: { id: string; label: string }[] = data?.available_models || [];

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api("/training/ai-config", { method: "PUT", body }),
    onSuccess: (res, body) => {
      qc.setQueryData(["training-ai-config"], res);
      qc.invalidateQueries({ queryKey: ["training-plans"] });
      if (body.api_key || body.clear_api_key) { setApiKey(""); toast(body.clear_api_key ? "Key removed" : "Key saved"); } else setSavedAt(Date.now());
    },
    onError: (e: Error) => toast(e.message, true),
  });
  const saveBudget = useDebouncedCallback((v: string) => { if (Number(v) >= 0.5) save.mutate({ monthly_budget_usd: Number(v) }); }, 800);
  const modelSelect = (label: string, hint: string, key: "model_fast" | "model_pro") => (
    <label className="field">{label}
      <select value={data?.[key] ?? ""} onChange={(e) => save.mutate({ [key]: e.target.value })}>
        {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        {data?.[key] && !models.some((m) => m.id === data[key]) && <option value={data[key]}>{data[key]}</option>}
      </select>
      <span className="xs muted" style={{ fontWeight: 400 }}>{hint}</span>
    </label>
  );
  const spent = data?.usage?.spent_usd ?? 0;
  const cap = data?.monthly_budget_usd ?? 8;
  const st = data?.status || {};
  const test = useMutation({
    mutationFn: () => api<any>("/training/ai-config/test", { method: "POST" }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["training-ai-config"] });
      toast(res.ok ? `Gemini answered in ${res.latency_s} s` : `Gemini did not answer: ${res.error}`, !res.ok);
    },
    onError: (e: Error) => toast(e.message, true),
  });
  const health = !data?.configured ? { s: "planned", l: "No key" }
    : test.isPending ? { s: "running", l: "Testing" }
      : st.last_ok === true ? { s: "completed", l: "Working" }
        : st.last_ok === false ? { s: "failed", l: "Not answering" } : { s: "planned", l: "Not tested yet" };

  return (
    <Card title="AI coach" icon={IconSparkles} hint="Writes and adapts plan sessions with Gemini, within a monthly spending cap"
      actions={<div className="row nowrap"><SavedMark at={savedAt} /><StatusBadge status={health.s} label={health.l} />
        {data?.key_source === "settings" && (
          <Menu><button className="danger" onClick={() => save.mutate({ clear_api_key: true })}><IconTrash size={ICON.button} />Remove saved key</button></Menu>
        )}
      </div>}>
      <div className="stack">
        {data?.configured && (
          <div className="row between wrap">
            <span className="xs muted">
              {st.last_ok === false
                ? <>Last try {ago(st.last_error_at)}: {st.last_error}. Plans are adapted with the built-in rules until it answers again.</>
                : st.last_ok_at ? <>Last answer {ago(st.last_ok_at)}, took {st.last_latency_s} s.</>
                  : <>Gemini hasn't been asked anything yet.</>}
            </span>
            <button className="sm" disabled={test.isPending} onClick={() => test.mutate()}>
              <IconRefresh size={ICON.button} className={test.isPending ? "spin" : undefined} />{test.isPending ? "Waiting for Gemini…" : "Test connection"}
            </button>
          </div>
        )}
        {data && (
          <div>
            <div className="pbar" style={{ "--pbar-color": spent / cap > 0.9 ? "var(--warn)" : "var(--text-secondary)" } as React.CSSProperties}>
              <span className="fill" style={{ width: `${Math.min(100, (spent / cap) * 100)}%` }} />
            </div>
            <div className="pbar-meta"><span>${spent.toFixed(2)} of ${cap.toFixed(2)} this month</span><span>{data.usage.calls} calls · {int(data.usage.input_tokens + data.usage.output_tokens)} tokens</span></div>
          </div>
        )}
        <label className="field">Gemini API key
          <div className="row nowrap">
            <input type="password" autoComplete="off" placeholder={data?.configured ? "Saved — paste a new key to replace it" : "Paste your key"} value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
            <button className="sm" disabled={!apiKey.trim() || save.isPending} onClick={() => save.mutate({ api_key: apiKey.trim() })}><IconKey size={ICON.button} />Save</button>
          </div>
          <span className="xs muted" style={{ fontWeight: 400 }}>AI Studio keys start with <span className="mono">AIza</span>, Vertex AI Express keys with <span className="mono">AQ.</span> — stored encrypted on this server.</span>
        </label>
        <div className="fields">
          <label className="field">Monthly cap (USD)
            <input type="number" step="0.5" min="0.5" max="100" value={budget ?? String(cap)} onChange={(e) => { setBudget(e.target.value); saveBudget(e.target.value); }} />
          </label>
          {models.length > 0 && modelSelect("Changes, feedback, reviews", "Quick thinking", "model_fast")}
          {models.length > 0 && modelSelect("Writing sessions", "Thinks longer", "model_pro")}
        </div>
        <ul className="xs muted plain-list">
          <li>Writes the sessions of the next two weeks as they come up, with your zones.</li>
          <li>Adapts the next 14 days after each sync, a skipped session or your note.</li>
          <li>Comments on each workout matched to the plan, and reviews every week on Sunday evening.</li>
          <li>All numbers come from RoutePass; changes that break the plan's rules are refused.</li>
        </ul>
      </div>
    </Card>
  );
}
