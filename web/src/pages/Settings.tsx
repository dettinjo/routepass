import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { BrandIcon, IconApi, IconRefresh, IconTarget, IconImport, IconUser } from "../components/icons";
import { Callout, Card, Seg, Skeleton, useToast } from "../components/ui";
import { StravaArchive } from "../components/StravaArchive";
import { AppearanceCard, GoalsCard, PlacesCard } from "../components/SettingsExtras";
import { GoogleCalendarCard, PushNotificationsCard } from "../components/TrainingIntegrations";
import { api, type Me } from "../lib/api";
import { clearOfflineData } from "../lib/pwa";
import { useQuery } from "@tanstack/react-query";
import { ago, int } from "../lib/format";
import { usePrefs, useSavePrefs, useStatus } from "../lib/hooks";

function useCall() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: ({ path, method = "POST", body }: { path: string; method?: string; body?: unknown }) => api(path, { method, body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["status"] }),
    onError: (e: Error) => toast(e.message, true),
  });
}

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
  const connect = async () => {
    try {
      const r = await api<{ url: string; redirect_uri: string }>("/connections/strava/authorize");
      setRedirect(r.redirect_uri);
      window.location.assign(r.url);
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const rate = status?.strava_rate;
  const modeLabel = s?.mode === "web" ? "web session" : s?.mode === "oauth+web" ? "OAuth + web fallback" : null;
  return (
    <Card title={<span className="row nowrap"><BrandIcon provider="strava" size={22} />Strava</span>}
      actions={s?.error ? <span className="badge bad">error</span> : s?.connected ? <span className="badge good">connected{modeLabel ? ` (${modeLabel})` : ""}</span> : <span className="badge">not connected</span>}>
      <div className="stack">
        {s?.error && <Callout kind="bad"><b>{s.error.hint}</b><div className="xs muted" style={{ marginTop: 4, wordBreak: "break-word" }}>{s.error.message}</div></Callout>}
        {s?.connected && s.athlete && (
          <div className="row between">
            <span>{s.athlete.name || `Athlete ${s.athlete.id}`} <span className="small muted">· since {ago(s.athlete.connected_at)}</span></span>
            <div className="row">
              <button className="sm" onClick={() => call.mutate({ path: "/connections/strava/check", method: "GET" }, { onSuccess: () => toast("Strava connection works") })}>Test</button>
              <button className="sm danger" onClick={() => confirm("Disconnect Strava?") && call.mutate({ path: "/connections/strava", method: "DELETE" })}>Disconnect</button>
            </div>
          </div>
        )}
        <div className="stack" style={{ gap: 8 }}>
          <p className="small muted" style={{ margin: 0 }}>
            Sign in normally on <span className="mono">strava.com</span> (<b>Email 6-digit One-Time Code</b>, <b>Google</b>, <b>Apple</b>, or password) — no paid Strava API required. Install the tiny 1-click userscript once (on Chrome/Edge requires <a href="https://chromewebstore.google.com/detail/tampermonkey-beta/gcalenpjmijncebpfijmoaglllgpjagf" target="_blank" rel="noreferrer">Tampermonkey BETA</a> for <span className="mono">GM_cookie</span>; on Firefox/Safari regular Tampermonkey works), then click <b>Sign in to Strava</b>.
          </p>
          <div className="row" style={{ gap: 8 }}>
            <a className="button sm" href="/api/v1/connections/strava/userscript.user.js" target="_blank" rel="noreferrer">
              1. Install 1-click connector (.user.js)
            </a>
            <a className="button primary sm" href="https://www.strava.com/dashboard#routepass-connect" target="_blank" rel="noreferrer">
              <BrandIcon provider="strava" size={15} />
              {s?.mode === "web" || s?.mode === "oauth+web" ? "2. Refresh Strava sign-in" : "2. Sign in to Strava"}
            </a>
            {(s?.mode === "web" || s?.mode === "oauth+web") && (
              <button className="sm ghost" type="button" onClick={() => call.mutate({ path: "/connections/strava/session", method: "DELETE" }, { onSuccess: () => toast("Strava web session removed") })}>
                Remove web session
              </button>
            )}
          </div>
        </div>
        <details>
          <summary className="small secondary" style={{ cursor: "pointer" }}>
            Advanced: paste session cookie or <span className="mono">Copy as cURL</span> manually
          </summary>
          <div className="stack mt8">
            <p className="small muted" style={{ margin: 0 }}>
              If you prefer to copy a session from your own desktop browser: in DevTools right-click any <span className="mono">strava.com</span> request in <b>Network → Copy → Copy as cURL</b> (or copy <span className="mono">_strava4_session</span> / <span className="mono">strava_remember_token</span> from <b>Application → Cookies</b>), and paste below.
            </p>
            <div className="fields">
              <label className="field">Session cookie, <span className="mono">Cookie:</span> header, or <span className="mono">Copy as cURL</span>
                <input type="password" placeholder="Paste _strava4_session, Cookie header, or Copy as cURL…" value={sessionCookie} onChange={(e) => setSessionCookie(e.target.value)} />
              </label>
              <label className="field">Remember token (<span className="mono">strava_remember_token</span>, optional if included above)
                <input type="password" placeholder="optional long-lived token" value={rememberToken} onChange={(e) => setRememberToken(e.target.value)} />
              </label>
            </div>
            <div className="row">
              <button className="sm" disabled={!sessionCookie.trim() && !rememberToken.trim()} onClick={() => call.mutate({ path: "/connections/strava/session", method: "PUT", body: { cookie: sessionCookie, remember_token: rememberToken } }, { onSuccess: () => { setSessionCookie(""); setRememberToken(""); toast("Strava web session connected"); } })}>
                Save cookie manually
              </button>
            </div>
          </div>
        </details>
        <details>
          <summary className="small secondary" style={{ cursor: "pointer" }}>Strava OAuth API application (requires paid Strava subscription)</summary>
          <div className="stack mt8">
            <p className="small muted" style={{ margin: 0 }}>
              Uses your own app from <a href="https://www.strava.com/settings/api" target="_blank" rel="noreferrer">strava.com/settings/api</a>. Set its
              “Authorization Callback Domain” to this host. Leave empty to keep the values from the environment.
            </p>
            <div className="fields">
              <label className="field">Client ID<input value={appId} onChange={(e) => setAppId(e.target.value)} /></label>
              <label className="field">Client secret<input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} /></label>
            </div>
            <div className="row">
              <button className="sm" disabled={!appId || !secret} onClick={() => call.mutate({ path: "/connections/strava/app", method: "PUT", body: { client_id: appId, client_secret: secret } }, { onSuccess: () => toast("Saved Strava app") })}>Save app</button>
              <button className="sm" onClick={connect}>{s?.connected ? "Reconnect OAuth" : "Connect OAuth"}</button>
            </div>
          </div>
        </details>
        <details>
          <summary className="small secondary" style={{ cursor: "pointer" }}>Redirect can't reach this host? Paste the OAuth code</summary>
          <div className="stack mt8">
            <p className="small muted" style={{ margin: 0 }}>After approving on Strava, copy the <span className="mono">code=…</span> value from the address bar of the page Strava sent you to.{redirect && <> Redirect used: <span className="mono">{redirect}</span></>}</p>
            <div className="row">
              <input placeholder="code" value={code} onChange={(e) => setCode(e.target.value)} />
              <button className="sm" disabled={!code} onClick={() => call.mutate({ path: "/connections/strava/code", body: { code } }, { onSuccess: () => { setCode(""); toast("Strava connected"); } })}>Finish</button>
            </div>
          </div>
        </details>
        {s?.connected && status?.public_url && (
          <div className="row between">
            <span className="secondary">Instant sync via Strava webhook</span>
            <div className="row">
              <button className="sm" onClick={() => call.mutate({ path: "/connections/strava/webhook", method: "GET" }, { onSuccess: (r: any) => toast(r.active ? `Webhook active${r.last_event ? ", last event " + ago(r.last_event.received_at) : ""}` : "Webhook not active") })}>Status</button>
              <button className="sm" onClick={() => call.mutate({ path: "/connections/strava/webhook", method: "PUT" }, { onSuccess: () => toast("Strava webhook enabled") })}>Enable</button>
              <button className="sm ghost" onClick={() => call.mutate({ path: "/connections/strava/webhook", method: "DELETE" }, { onSuccess: () => toast("Strava webhook removed") })}>Disable</button>
            </div>
          </div>
        )}
        <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}><StravaArchive /></div>
        {rate?.observed_at && (
          <div className="small muted">
            API usage — 15 min: {rate.overall["15min"][0]}/{rate.overall["15min"][1]} (read {rate.read["15min"][0]}/{rate.read["15min"][1]}) ·
            today: {rate.overall.day[0]}/{rate.overall.day[1]} (read {rate.read.day[0]}/{rate.read.day[1]})
          </div>
        )}
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
  const k = status?.connections.komoot;
  return (
    <Card title={<span className="row nowrap"><BrandIcon provider="komoot" size={22} />Komoot</span>}
      actions={k?.error ? <span className="badge bad">error</span> : k?.connected ? <span className="badge good">connected</span> : <span className="badge">not connected</span>}>
      <div className="stack">
        {k?.error && <Callout kind="bad"><b>{k.error.hint}</b><div className="xs muted" style={{ marginTop: 4, wordBreak: "break-word" }}>{k.error.message}</div></Callout>}
        {k?.connected && k.account && (
          <div className="row between">
            <span>{k.account.display_name || k.account.email} <span className="small muted">· user {k.account.user_id}</span></span>
            <button className="sm danger" onClick={() => confirm("Disconnect Komoot?") && call.mutate({ path: "/connections/komoot", method: "DELETE" })}>Disconnect</button>
          </div>
        )}
        <p className="small muted" style={{ margin: 0 }}>Komoot has no public API; RoutePass signs in with your email and password (stored encrypted on this server).</p>
        <form className="fields" style={{ alignItems: "end" }} onSubmit={(e) => { e.preventDefault(); call.mutate({ path: "/connections/komoot", method: "PUT", body: { email, password } }, { onSuccess: () => { setPassword(""); toast("Komoot connected"); } }); }}>
          <label className="field">Email<input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          <label className="field">Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
          <div><button className="primary" type="submit" disabled={!email || !password || call.isPending}>{k?.connected ? "Update login" : "Connect Komoot"}</button></div>
        </form>
      </div>
    </Card>
  );
}

function NumberField({ label, value, onSave, step, min, placeholder }: { label: string; value: number | null; onSave: (v: number | null) => void; step?: number; min?: number; placeholder?: string }) {
  const [v, setV] = useState(value == null ? "" : String(value));
  useEffect(() => setV(value == null ? "" : String(value)), [value]);
  return (
    <label className="field">{label}
      <input type="number" step={step} min={min} placeholder={placeholder} value={v} onChange={(e) => setV(e.target.value)} onBlur={() => { const n = v === "" ? null : Number(v); if (n !== value) onSave(n); }} />
    </label>
  );
}

export default function Settings() {
  const { data: prefs } = usePrefs();
  const save = useSavePrefs();
  const { data: status } = useStatus();
  const [sp] = useSearchParams();
  const toast = useToast();
  const call = useCall();
  const { data: me } = useQuery<Me>({ queryKey: ["me"], queryFn: () => api("/auth/me") });
  useEffect(() => {
    if (sp.get("strava") === "connected") toast("Strava connected — first import is running");
    if (sp.get("strava") === "error") toast(`Strava connection failed (${sp.get("reason")})`, true);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const { data: st } = useStatus();
  const origin = window.location.origin;
  const apiBase = st?.public_url || origin;
  const mcpConfig = JSON.stringify({ mcpServers: { routepass: { type: "http", url: `${apiBase}/mcp`, headers: { Authorization: "Bearer <ROUTEPASS_LOCAL_API_TOKEN>" } } } }, null, 2);

  return (
    <>
      <div className="page-head"><div><h1>Settings</h1><div className="sub">Connections, athlete profile, matching and API access</div></div></div>
      <div className="stack gap16">
        {me?.authenticated && (
          <Card title="Account" icon={IconUser}
            actions={me.method !== "tailscale" && <button className="sm" onClick={async () => { await fetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin" }); await clearOfflineData(); window.location.replace("/login"); }}>Sign out</button>}>
            <div className="row nowrap" style={{ gap: 12 }}>
              {me.picture ? <img src={me.picture} alt="" width={40} height={40} style={{ borderRadius: "50%" }} referrerPolicy="no-referrer" /> : <span className="card-ico" style={{ width: 40, height: 40, borderRadius: 20 }}><IconUser size={20} /></span>}
              <div className="grow">
                <b>{me.name || me.email || "Signed in"}</b>
                <div className="small muted">{me.email ? `${me.email} · ` : ""}{{ google: "signed in with Google", tailscale: "signed in automatically via Tailscale", token: "signed in with the access token", open: "no sign-in required" }[me.method ?? ""] ?? me.method}</div>
              </div>
            </div>
          </Card>
        )}
        <div className="grid g2"><Strava /><Komoot /></div>

        {!prefs ? <Skeleton h={200} /> : (
          <>
            <Card title="Athlete profile" icon={IconUser} hint="Drives zones and training load. Changing it recomputes every activity.">
              <div className="fields">
                <NumberField label="FTP (W)" value={prefs.profile.ftp} onSave={(v) => save.mutate({ profile: { ftp: v } })} />
                <NumberField label="Max heart rate (bpm)" value={prefs.profile.hr_max} onSave={(v) => save.mutate({ profile: { hr_max: v } })} />
                <NumberField label="Resting heart rate (bpm)" value={prefs.profile.hr_rest} onSave={(v) => save.mutate({ profile: { hr_rest: v } })} />
                <NumberField label="Weight (kg)" value={prefs.profile.weight_kg} step={0.1} onSave={(v) => save.mutate({ profile: { weight_kg: v } })} />
              </div>
            </Card>
            <div className="grid g2">
              <Card title="Duplicate detection" icon={IconTarget} hint="Records from both platforms are the same activity when these match">
                <div className="fields">
                  <NumberField label="Start time within (minutes)" value={prefs.matching.time_tolerance_min} onSave={(v) => save.mutate({ matching: { time_tolerance_min: v ?? 10 } })} />
                  <NumberField label="Distance within (%)" value={prefs.matching.distance_tolerance_pct} onSave={(v) => save.mutate({ matching: { distance_tolerance_pct: v ?? 15 } })} />
                </div>
                <p className="small muted" style={{ marginBottom: 0 }}>Wrong match? Use “Not the same” or “Merge” on the activity page — manual decisions are kept.</p>
              </Card>
              <Card title="Import" icon={IconImport} hint="What is read from the platforms">
                <div className="fields">
                  <label className="field">History starts at
                    <input type="date" value={prefs.import.history_start ?? ""} onChange={(e) => save.mutate({ import: { history_start: e.target.value || null } })} />
                  </label>
                </div>
                <div className="stack" style={{ gap: 6 }}>
                  <span className="small secondary">Sync automatically</span>
                  <Seg block value={String(prefs.poll_interval_minutes ?? 30)} onChange={(v) => save.mutate({ poll_interval_minutes: Number(v) })}
                    options={[{ value: "0", label: "Manual" }, { value: "30", label: "30 min" }, { value: "60", label: "1 h" }, { value: "120", label: "2 h" }, { value: "360", label: "6 h" }]} />
                  <span className="xs muted">{(prefs.poll_interval_minutes ?? 30) === 0 ? "Only when you press Sync now (queued copies still finish in the background)." : "Plus Sync now any time, and instantly via the Strava webhook when it is enabled."}</span>
                </div>
                {status && (
                  <p className="small muted" style={{ marginBottom: 0 }}>
                    {int(status.coverage.provider_records.strava ?? 0)} Strava + {int(status.coverage.provider_records.komoot ?? 0)} Komoot records → {int(status.activities)} activities.
                    {status.tracks_pending > 0 && ` ${int(status.tracks_pending)} recordings still downloading (rate-limited in the background).`}
                  </p>
                )}
              </Card>
            </div>
            <GoalsCard prefs={prefs} onSave={(goals) => save.mutate({ goals })} />
            <PlacesCard places={prefs.places ?? []} onSave={(places) => save.mutate({ places })} />
          </>
        )}
        <AppearanceCard />
        <GeminiAICard />
        <GoogleCalendarCard />
        <PushNotificationsCard />

        <Card title="API & MCP" icon={IconApi} hint="Everything in this UI is available programmatically">
          <div className="stack">
            <dl className="kv">
              <dt>REST API</dt><dd><a href="/api/docs" target="_blank" rel="noreferrer" className="mono">{origin}/api/v1</a> · <a href="/api/docs" target="_blank" rel="noreferrer">interactive docs</a></dd>
              <dt>MCP</dt><dd className="mono">{origin}/mcp</dd>
              {st?.public_url && <><dt>Public (API only)</dt><dd className="mono">{st.public_url}/api/v1 · {st.public_url}/mcp</dd></>}
              <dt>Auth</dt><dd>Header <span className="mono">Authorization: Bearer &lt;ROUTEPASS_LOCAL_API_TOKEN&gt;</span> (the web UI uses your sign-in instead)</dd>
            </dl>
            <div className="section-label">MCP client config</div>
            <pre className="mono callout" style={{ margin: 0, overflowX: "auto" }}>{mcpConfig}</pre>

          </div>
        </Card>

        <Card title="Maintenance" icon={IconRefresh}>
          <div className="row">
            <button onClick={() => call.mutate({ path: "/settings/recompute" }, { onSuccess: () => toast("Recomputing all tracks in the background") })}>Recompute analysis</button>
            <button onClick={() => call.mutate({ path: "/sync/run", body: { full: true } }, { onSuccess: () => toast("Full rescan started") })}>Full rescan</button>
          </div>
        </Card>
      </div>
    </>
  );
}

function GeminiAICard() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery<any>({
    queryKey: ["training-ai-config"],
    queryFn: () => api("/training/ai-config"),
  });
  const [apiKey, setApiKey] = useState("");
  const [budget, setBudget] = useState("");

  useEffect(() => {
    if (data?.monthly_budget_usd != null && budget === "") {
      setBudget(String(data.monthly_budget_usd));
    }
  }, [data, budget]);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api("/training/ai-config", { method: "PUT", body }),
    onSuccess: (res) => {
      qc.setQueryData(["training-ai-config"], res);
      qc.invalidateQueries({ queryKey: ["training-plans"] });
      setApiKey("");
      toast("Saved Gemini AI Coach settings");
    },
    onError: (e: Error) => toast(e.message, true),
  });

  return (
    <Card
      title="AI Coach (Gemini)"
      hint="Powers adaptive training plans using your Google Cloud credits with a hard monthly spend cap"
      actions={
        data?.configured ? (
          <span className="badge good">connected ({data.key_source})</span>
        ) : (
          <span className="badge">not configured</span>
        )
      }
    >
      <div className="stack">
        {data && (
          <div className="row between xs muted" style={{ flexWrap: "wrap", gap: 8 }}>
            <span>
              Month <b>{data.usage.month}</b>: <b>${data.usage.spent_usd.toFixed(4)}</b> / ${data.monthly_budget_usd.toFixed(2)} USD
              ({data.usage.calls} calls · {int(data.usage.input_tokens + data.usage.output_tokens)} tokens)
            </span>
            <span>
              Models: <span className="mono">{data.model_fast}</span> / <span className="mono">{data.model_pro}</span>
            </span>
          </div>
        )}
        <div className="fields">
          <label className="field">
            Gemini API Key (Vertex AI Express <span className="mono">AQ.…</span> or AI Studio <span className="mono">AIza…</span>)
            <input
              type="password"
              placeholder={data?.configured ? "Saved (paste new key to replace)" : "Paste key or set ROUTEPASS_GEMINI_API_KEY"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </label>
          <label className="field">
            Monthly Budget Cap (USD)
            <input
              type="number"
              step="0.5"
              min="0.5"
              max="100"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
            />
          </label>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button
            className="sm primary"
            disabled={save.isPending}
            onClick={() =>
              save.mutate({
                ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
                ...(budget ? { monthly_budget_usd: Number(budget) } : {}),
              })
            }
          >
            Save AI settings
          </button>
          {data?.key_source === "settings" && (
            <button
              className="sm ghost danger"
              disabled={save.isPending}
              onClick={() => save.mutate({ clear_api_key: true })}
            >
              Remove saved key
            </button>
          )}
        </div>
      </div>
    </Card>
  );
}
