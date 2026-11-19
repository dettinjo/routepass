import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ComponentType, type ReactNode } from "react";
import { Link, NavLink, useParams, useSearchParams } from "react-router-dom";
import { DataQualityNote } from "../components/DataQuality";
import {
  BrandIcon, ICON, IconCode2, IconConnections, IconCopy2, IconExternal, IconImport, IconKey, IconLeft, IconLogout2, IconPhone,
  IconRefresh, IconRight, IconSliders, IconSync, IconTarget, IconTraining, IconTrash, IconUser,
} from "../components/icons";
import { StravaArchive } from "../components/StravaArchive";
import { AppearanceCard, GoalsCard, PlacesCard } from "../components/SettingsExtras";
import { AICoachCard, GoogleCalendarCard, PushNotificationsCard } from "../components/TrainingIntegrations";
import { Callout, Card, Menu, SavedMark, Seg, Skeleton, StatusBadge, useToast } from "../components/ui";
import { api, type Me } from "../lib/api";
import { ago, int } from "../lib/format";
import { usePrefs, useSavePrefs, useStatus } from "../lib/hooks";
import { clearOfflineData } from "../lib/pwa";

type Section = "connections" | "profile" | "sync" | "training" | "app" | "developer";
const SECTIONS: { value: Section; label: string; sub: string; icon: ComponentType<{ size?: number }> }[] = [
  { value: "connections", label: "Connections", sub: "Strava, Komoot, Google Calendar, Strava export", icon: IconConnections },
  { value: "profile", label: "Profile & goals", sub: "Heart rate, FTP, weight, goals, places", icon: IconUser },
  { value: "sync", label: "Sync & matching", sub: "Schedule, history, duplicate detection", icon: IconSliders },
  { value: "training", label: "Training & AI", sub: "AI coach, reminders", icon: IconTraining },
  { value: "app", label: "App & account", sub: "Appearance, install, sign out", icon: IconPhone },
  { value: "developer", label: "API & MCP", sub: "Access for scripts and assistants, maintenance", icon: IconCode2 },
];

function useCall() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: ({ path, method = "POST", body }: { path: string; method?: string; body?: unknown }) => api(path, { method, body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["status"] }),
    onError: (e: Error) => toast(e.message, true),
  });
}

function ConnStatus({ connected, error }: { connected?: boolean; error?: boolean }) {
  return error ? <StatusBadge status="error" label="Needs attention" /> : connected ? <StatusBadge status="completed" label="Connected" /> : <StatusBadge status="planned" label="Not connected" />;
}

// ── connections ───────────────────────────────────────────────────────────────
function Strava() {
  const { data: status } = useStatus();
  const call = useCall();
  const toast = useToast();
  const [appId, setAppId] = useState("");
  const [secret, setSecret] = useState("");
  const [code, setCode] = useState("");
  const [sessionCookie, setSessionCookie] = useState("");
  const [rememberToken, setRememberToken] = useState("");
  const [redirect, setRedirect] = useState<string | null>(null);
  const s = status?.connections.strava;
  const web = s?.mode === "web" || s?.mode === "oauth+web";
  const connectOAuth = async () => {
    try {
      const r = await api<{ url: string; redirect_uri: string }>("/connections/strava/authorize");
      setRedirect(r.redirect_uri);
      window.location.assign(r.url);
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const rate = status?.strava_rate;
  const signIn = (
    <a className="btn primary sm" href="https://www.strava.com/dashboard#routepass-connect" target="_blank" rel="noreferrer">
      <BrandIcon provider="strava" size={ICON.button} mono />{s?.connected ? "Refresh Strava sign-in" : "Sign in on Strava"}
    </a>
  );
  return (
    <Card title={<span className="row nowrap"><BrandIcon provider="strava" size={22} />Strava</span>}
      actions={<div className="row nowrap"><ConnStatus connected={s?.connected} error={Boolean(s?.error)} />
        {s?.connected && (
          <Menu>
            <button onClick={() => call.mutate({ path: "/connections/strava/check", method: "GET" }, { onSuccess: () => toast("Strava connection works") })}><IconRefresh size={ICON.button} />Test connection</button>
            <a href="/api/v1/connections/strava/userscript.user.js" target="_blank" rel="noreferrer"><IconImport size={ICON.button} />Reinstall connector</a>
            {status?.public_url && <>
              <div className="sep" />
              <div className="meta">Instant sync via webhook</div>
              <button onClick={() => call.mutate({ path: "/connections/strava/webhook", method: "GET" }, { onSuccess: (r: any) => toast(r.active ? `Webhook active${r.last_event ? ", last event " + ago(r.last_event.received_at) : ""}` : "Webhook not active") })}>Webhook status</button>
              <button onClick={() => call.mutate({ path: "/connections/strava/webhook", method: "PUT" }, { onSuccess: () => toast("Strava webhook enabled") })}>Enable webhook</button>
              <button onClick={() => call.mutate({ path: "/connections/strava/webhook", method: "DELETE" }, { onSuccess: () => toast("Strava webhook removed") })}>Disable webhook</button>
            </>}
            <div className="sep" />
            {web && <button onClick={() => call.mutate({ path: "/connections/strava/session", method: "DELETE" }, { onSuccess: () => toast("Browser session removed") })}><IconTrash size={ICON.button} />Remove browser session</button>}
            <button className="danger" onClick={() => confirm("Disconnect Strava? Imported activities stay.") && call.mutate({ path: "/connections/strava", method: "DELETE" })}><IconTrash size={ICON.button} />Disconnect Strava</button>
          </Menu>
        )}
      </div>}>
      <div className="stack">
        {s?.error && (
          <Callout kind="bad">
            <div className="stack" style={{ gap: 8 }}>
              <b>{s.error.hint}</b>
              <span className="xs muted" style={{ wordBreak: "break-word" }}>{s.error.message}</span>
              <div>{signIn}</div>
            </div>
          </Callout>
        )}
        {s?.connected ? (
          <div className="conn-row">
            <div className="grow">
              <b>{s.athlete?.name || "Strava athlete"}</b>
              <div className="small muted">{s.athlete?.id ? `#${s.athlete.id} · ` : ""}{web ? "via your browser session" : "via the Strava API"} · since {ago(s.athlete?.connected_at)}</div>
            </div>
            {!s.error && web && signIn}
          </div>
        ) : (
          <div className="stack" style={{ gap: 10 }}>
            <p className="small secondary">No paid Strava API needed: a small browser add-on hands your Strava sign-in to RoutePass and keeps it fresh.</p>
            <div className="row">
              <a className="btn sm" href="/api/v1/connections/strava/userscript.user.js" target="_blank" rel="noreferrer"><IconImport size={ICON.button} />1. Install connector</a>
              {signIn}
            </div>
            <span className="xs muted">Needs <a href="https://www.tampermonkey.net/" target="_blank" rel="noreferrer">Tampermonkey</a> on a desktop browser (Chrome/Edge: the BETA version). Installing again replaces the previous connector.</span>
          </div>
        )}
        <details className="more">
          <summary><IconRight size={ICON.button} />Other ways to connect</summary>
          <div className="stack mt8" style={{ gap: 16 }}>
            <div className="stack" style={{ gap: 8 }}>
              <b className="small">Paste a session cookie</b>
              <p className="xs muted">In your browser's developer tools copy any strava.com request as cURL (or the <span className="mono">_strava4_session</span> and <span className="mono">strava_remember_token</span> cookies).</p>
              <div className="fields">
                <label className="field">Cookie, Cookie header or cURL<input type="password" value={sessionCookie} onChange={(e) => setSessionCookie(e.target.value)} /></label>
                <label className="field">Remember token (optional)<input type="password" value={rememberToken} onChange={(e) => setRememberToken(e.target.value)} /></label>
              </div>
              <div><button className="sm" disabled={!sessionCookie.trim() && !rememberToken.trim()} onClick={() => call.mutate({ path: "/connections/strava/session", method: "PUT", body: { cookie: sessionCookie, remember_token: rememberToken } }, { onSuccess: () => { setSessionCookie(""); setRememberToken(""); toast("Strava connected"); } })}><IconKey size={ICON.button} />Save cookie</button></div>
            </div>
            <div className="stack" style={{ gap: 8 }}>
              <b className="small">Your own Strava API application</b>
              <p className="xs muted">Needs a paid Strava subscription. Create it at <a href="https://www.strava.com/settings/api" target="_blank" rel="noreferrer">strava.com/settings/api</a> with this host as callback domain.</p>
              <div className="fields">
                <label className="field">Client ID<input value={appId} onChange={(e) => setAppId(e.target.value)} /></label>
                <label className="field">Client secret<input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} /></label>
              </div>
              <div className="row">
                <button className="sm" disabled={!appId || !secret} onClick={() => call.mutate({ path: "/connections/strava/app", method: "PUT", body: { client_id: appId, client_secret: secret } }, { onSuccess: () => toast("Saved Strava app") })}><IconKey size={ICON.button} />Save app</button>
                <button className="sm" onClick={connectOAuth}><IconExternal size={ICON.button} />{s?.mode === "oauth" || s?.mode === "oauth+web" ? "Reconnect" : "Connect"} with the API</button>
              </div>
              <div className="row nowrap">
                <input placeholder="OAuth code, if the redirect cannot reach this host" value={code} onChange={(e) => setCode(e.target.value)} />
                <button className="sm" disabled={!code} onClick={() => call.mutate({ path: "/connections/strava/code", body: { code } }, { onSuccess: () => { setCode(""); toast("Strava connected"); } })}>Finish</button>
              </div>
              {redirect && <span className="xs muted">Redirect used: <span className="mono">{redirect}</span></span>}
            </div>
            {rate?.observed_at && (
              <span className="xs muted">API usage — 15 min: {rate.overall["15min"][0]}/{rate.overall["15min"][1]} · today: {rate.overall.day[0]}/{rate.overall.day[1]}</span>
            )}
          </div>
        </details>
      </div>
    </Card>
  );
}

function Komoot() {
  const { data: status } = useStatus();
  const call = useCall();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [editing, setEditing] = useState(false);
  const k = status?.connections.komoot;
  const showForm = !k?.connected || editing || Boolean(k?.error);
  return (
    <Card title={<span className="row nowrap"><BrandIcon provider="komoot" size={22} />Komoot</span>}
      actions={<div className="row nowrap"><ConnStatus connected={k?.connected} error={Boolean(k?.error)} />
        {k?.connected && (
          <Menu>
            <button onClick={() => setEditing(true)}><IconKey size={ICON.button} />Change login</button>
            <div className="sep" />
            <button className="danger" onClick={() => confirm("Disconnect Komoot? Imported activities stay.") && call.mutate({ path: "/connections/komoot", method: "DELETE" })}><IconTrash size={ICON.button} />Disconnect Komoot</button>
          </Menu>
        )}
      </div>}>
      <div className="stack">
        {k?.error && <Callout kind="bad"><b>{k.error.hint}</b><div className="xs muted" style={{ marginTop: 4, wordBreak: "break-word" }}>{k.error.message}</div></Callout>}
        {k?.connected && k.account && (
          <div className="conn-row">
            <div className="grow"><b>{k.account.display_name || k.account.email}</b><div className="small muted">user {k.account.user_id}</div></div>
          </div>
        )}
        {showForm && (
          <>
            <p className="small secondary">Komoot has no public API, so RoutePass signs in with your email and password (stored encrypted on this server).</p>
            <form className="fields" style={{ alignItems: "end" }} onSubmit={(e) => { e.preventDefault(); call.mutate({ path: "/connections/komoot", method: "PUT", body: { email, password } }, { onSuccess: () => { setPassword(""); setEditing(false); toast("Komoot connected"); } }); }}>
              <label className="field">Email<input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
              <label className="field">Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
              <div className="row">
                <button className="primary" type="submit" disabled={!email || !password || call.isPending}><IconKey size={ICON.button} />{k?.connected ? "Update login" : "Connect Komoot"}</button>
                {editing && <button type="button" className="ghost" onClick={() => setEditing(false)}>Cancel</button>}
              </div>
            </form>
          </>
        )}
      </div>
    </Card>
  );
}

// ── profile ──────────────────────────────────────────────────────────────────
function NumberField({ label, value, onSave, step, min, placeholder, hint }: { label: string; value: number | null; onSave: (v: number | null) => void; step?: number; min?: number; placeholder?: string; hint?: ReactNode }) {
  const [v, setV] = useState(value == null ? "" : String(value));
  useEffect(() => setV(value == null ? "" : String(value)), [value]);
  return (
    <label className="field">{label}
      <input type="number" inputMode="decimal" step={step} min={min} placeholder={placeholder} value={v} onChange={(e) => setV(e.target.value)} onBlur={() => { const n = v === "" ? null : Number(v); if (n !== value) onSave(n); }} />
      {hint && <span className="xs muted" style={{ fontWeight: 400 }}>{hint}</span>}
    </label>
  );
}

function ProfileSection() {
  const { data: prefs } = usePrefs();
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [goalsAt, setGoalsAt] = useState<number | null>(null);
  const save = useSavePrefs({ quiet: true, onSaved: () => setSavedAt(Date.now()) });
  const saveGoals = useSavePrefs({ quiet: true, onSaved: () => setGoalsAt(Date.now()) });
  const savePlaces = useSavePrefs();
  const { data: dq } = useQuery<any>({ queryKey: ["data-quality"], queryFn: () => api("/insights/data-quality"), staleTime: 60_000 });
  if (!prefs) return <Skeleton h={300} />;
  const suggest = (v: number | null | undefined, unit: string) => (v ? <>Your recordings suggest {v} {unit}</> : undefined);
  return (
    <>
      <DataQualityNote />
      <Card title="Athlete profile" icon={IconUser} hint="Drives zones and training load. Changing it recomputes every activity." actions={<SavedMark at={savedAt} />}>
        <div className="fields">
          <NumberField label="Max heart rate (bpm)" value={prefs.profile.hr_max} onSave={(v) => save.mutate({ profile: { hr_max: v } })} hint={suggest(dq?.suggestions?.hr_max, "bpm")} />
          <NumberField label="Resting heart rate (bpm)" value={prefs.profile.hr_rest} onSave={(v) => save.mutate({ profile: { hr_rest: v } })} />
          <NumberField label="FTP (W)" value={prefs.profile.ftp} onSave={(v) => save.mutate({ profile: { ftp: v } })} hint={suggest(dq?.suggestions?.ftp, "W")} />
          <NumberField label="Weight (kg)" value={prefs.profile.weight_kg} step={0.1} onSave={(v) => save.mutate({ profile: { weight_kg: v } })} />
        </div>
      </Card>
      <GoalsCard prefs={prefs} savedAt={goalsAt} onSave={(goals) => saveGoals.mutate({ goals })} />
      <PlacesCard places={prefs.places ?? []} onSave={(places) => savePlaces.mutate({ places })} />
    </>
  );
}

// ── sync ─────────────────────────────────────────────────────────────────────
function SyncSection() {
  const { data: prefs } = usePrefs();
  const { data: status } = useStatus();
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [matchAt, setMatchAt] = useState<number | null>(null);
  const save = useSavePrefs({ quiet: true, onSaved: () => setSavedAt(Date.now()) });
  const saveMatch = useSavePrefs({ quiet: true, onSaved: () => setMatchAt(Date.now()) });
  if (!prefs) return <Skeleton h={300} />;
  const poll = prefs.poll_interval_minutes ?? 30;
  return (
    <>
      <Card title="Sync rules & history" icon={IconSync} hint="Which activities are copied between Strava and Komoot">
        <Link to="/sync" className="btn sm"><IconSync size={ICON.button} />Open sync rules<IconRight size={ICON.button} /></Link>
      </Card>
      <Card title="Import" icon={IconImport} hint="What is read from the platforms, and how often" actions={<SavedMark at={savedAt} />}>
        <div className="stack">
          <div className="stack" style={{ gap: 6 }}>
            <span className="small secondary" style={{ fontWeight: 600 }}>Check for new activities</span>
            <Seg block value={String(poll)} onChange={(v) => save.mutate({ poll_interval_minutes: Number(v) })}
              options={[{ value: "0", label: "Manually" }, { value: "30", label: "30 min" }, { value: "60", label: "1 h" }, { value: "120", label: "2 h" }, { value: "360", label: "6 h" }]} />
            <span className="xs muted">{poll === 0 ? "Only when you press Sync now (queued copies still finish in the background)." : "Plus Sync now any time, and instantly via the Strava webhook when it is enabled."}</span>
          </div>
          <div className="fields">
            <label className="field">History starts at
              <input type="date" value={prefs.import.history_start ?? ""} onChange={(e) => save.mutate({ import: { history_start: e.target.value || null } })} />
            </label>
          </div>
          {status && (
            <p className="small muted">
              {int(status.coverage.provider_records.strava ?? 0)} Strava + {int(status.coverage.provider_records.komoot ?? 0)} Komoot records → {int(status.activities)} activities.
              {status.tracks_pending > 0 && ` ${int(status.tracks_pending)} recordings still downloading (rate-limited in the background).`}
            </p>
          )}
        </div>
      </Card>
      <Card title="Duplicate detection" icon={IconTarget} hint="Records from both platforms are the same activity when these match" actions={<SavedMark at={matchAt} />}>
        <div className="fields">
          <NumberField label="Start time within (minutes)" value={prefs.matching.time_tolerance_min} onSave={(v) => saveMatch.mutate({ matching: { time_tolerance_min: v ?? 10 } })} />
          <NumberField label="Distance within (%)" value={prefs.matching.distance_tolerance_pct} onSave={(v) => saveMatch.mutate({ matching: { distance_tolerance_pct: v ?? 15 } })} />
        </div>
        <p className="small muted mt8">Wrong match? Use “Not the same” or “Merge” on the activity page — manual decisions are kept.</p>
      </Card>
    </>
  );
}

// ── app & developer ──────────────────────────────────────────────────────────
function AccountCard() {
  const { data: me } = useQuery<Me>({ queryKey: ["me"], queryFn: () => api("/auth/me") });
  if (!me?.authenticated) return null;
  return (
    <Card title="Account" icon={IconUser}
      actions={me.method !== "tailscale" && <button className="sm" onClick={async () => { await fetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin" }); await clearOfflineData(); window.location.replace("/login"); }}><IconLogout2 size={ICON.button} />Sign out</button>}>
      <div className="row nowrap" style={{ gap: 12 }}>
        {me.picture ? <img src={me.picture} alt="" width={40} height={40} style={{ borderRadius: "50%" }} referrerPolicy="no-referrer" /> : <span className="card-ico" style={{ width: 40, height: 40, borderRadius: 20 }}><IconUser size={ICON.header} /></span>}
        <div className="grow">
          <b>{me.name || me.email || "Signed in"}</b>
          <div className="small muted">{me.email ? `${me.email} · ` : ""}{{ google: "signed in with Google", tailscale: "signed in automatically via Tailscale", token: "signed in with the access token", open: "no sign-in required" }[me.method ?? ""] ?? me.method}</div>
        </div>
      </div>
    </Card>
  );
}

function DeveloperSection() {
  const { data: st } = useStatus();
  const call = useCall();
  const toast = useToast();
  const origin = window.location.origin;
  const apiBase = st?.public_url || origin;
  const mcpConfig = JSON.stringify({ mcpServers: { routepass: { type: "http", url: `${apiBase}/mcp`, headers: { Authorization: "Bearer <ROUTEPASS_LOCAL_API_TOKEN>" } } } }, null, 2);
  return (
    <>
      <Card title="API & MCP" icon={IconCode2} hint="Everything in this app is available programmatically">
        <div className="stack">
          <dl className="kv">
            <dt>REST API</dt><dd><span className="mono">{origin}/api/v1</span> · <a href="/api/docs" target="_blank" rel="noreferrer">docs</a></dd>
            <dt>MCP</dt><dd className="mono">{origin}/mcp</dd>
            {st?.public_url && <><dt>From the internet</dt><dd className="mono">{st.public_url}/api/v1 · {st.public_url}/mcp</dd></>}
            <dt>Auth</dt><dd>Header <span className="mono">Authorization: Bearer &lt;ROUTEPASS_LOCAL_API_TOKEN&gt;</span></dd>
          </dl>
          <div className="row between"><span className="section-label">MCP client config</span>
            <button className="sm ghost" onClick={() => { navigator.clipboard?.writeText(mcpConfig); toast("Copied"); }}><IconCopy2 size={ICON.button} />Copy</button>
          </div>
          <pre className="mono callout" style={{ margin: 0, overflowX: "auto", display: "block" }}>{mcpConfig}</pre>
        </div>
      </Card>
      <Card title="Maintenance" icon={IconRefresh} hint="Rarely needed — both run in the background">
        <div className="row">
          <button className="sm" onClick={() => call.mutate({ path: "/settings/recompute" }, { onSuccess: () => toast("Recomputing all tracks in the background") })}><IconRefresh size={ICON.button} />Recompute analysis</button>
          <button className="sm" onClick={() => confirm("Re-read every activity from Strava and Komoot? This takes a while.") && call.mutate({ path: "/sync/run", body: { full: true } }, { onSuccess: () => toast("Full rescan started") })}><IconSync size={ICON.button} />Full rescan</button>
        </div>
      </Card>
    </>
  );
}

// ── page ─────────────────────────────────────────────────────────────────────
export default function Settings() {
  const { section } = useParams();
  const [sp] = useSearchParams();
  const toast = useToast();
  useEffect(() => {
    if (sp.get("strava") === "connected") toast("Strava connected — first import is running");
    if (sp.get("strava") === "error") toast(`Strava connection failed (${sp.get("reason")})`, true);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // Older links (Google Calendar OAuth return, ?strava=…) land on /settings: show connections.
  const fallback: Section = "connections";
  const current = (SECTIONS.some((s) => s.value === section) ? section : fallback) as Section;
  const meta = SECTIONS.find((s) => s.value === current)!;
  return (
    <>
      <div className={`page-head ${section ? "hide-mobile" : ""}`}>
        <div><h1>Settings</h1><div className="sub">Connections, profile, sync and access</div></div>
      </div>
      <div className="settings-layout">
        <nav className={`settings-nav ${section ? "hide-mobile" : ""}`} aria-label="Settings sections">
          <Link to="/sync" className="hide-desktop"><span className="card-ico"><IconSync size={ICON.header} /></span><span>Sync rules & history<span className="sub">Directions, rules, recent runs</span></span><IconRight size={ICON.button} className="chev" /></Link>
          {SECTIONS.map((s) => (
            <NavLink key={s.value} to={`/settings/${s.value}`} className={() => (s.value === current && (section || window.innerWidth >= 900) ? "active" : "")}>
              <span className="card-ico"><s.icon size={ICON.header} /></span>
              <span>{s.label}<span className="sub">{s.sub}</span></span>
              <IconRight size={ICON.button} className="chev" />
            </NavLink>
          ))}
        </nav>
        <div className={`stack gap16 ${section ? "" : "hide-mobile"}`} style={{ minWidth: 0 }}>
          <div className="hide-desktop">
            <Link to="/settings" className="back-link"><IconLeft size={ICON.button} />Settings</Link>
            <h1>{meta.label}</h1>
          </div>
          {current === "connections" && <>
            <div className="grid g2"><Strava /><Komoot /></div>
            <Card title="Import your Strava export" icon={IconImport} hint="Your complete Strava history, free and without the API"><StravaArchive /></Card>
            <GoogleCalendarCard />
          </>}
          {current === "profile" && <ProfileSection />}
          {current === "sync" && <SyncSection />}
          {current === "training" && <><AICoachCard /><PushNotificationsCard /></>}
          {current === "app" && <><AccountCard /><AppearanceCard /></>}
          {current === "developer" && <DeveloperSection />}
        </div>
      </div>
    </>
  );
}
