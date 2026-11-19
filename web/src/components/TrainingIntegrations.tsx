import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Callout, Card, useToast } from "./ui";

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const out = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) out[i] = rawData.charCodeAt(i);
  return out;
}

export function GoogleCalendarCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: cfg } = useQuery<any>({
    queryKey: ["gcal-config"],
    queryFn: () => api("/connections/google-calendar"),
  });
  const { data: calendars, refetch: refetchCals } = useQuery<any[]>({
    queryKey: ["gcal-calendars"],
    queryFn: () => api("/connections/google-calendar/calendars"),
    enabled: Boolean(cfg?.connected),
  });

  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [targetId, setTargetId] = useState("");
  const [busyIds, setBusyIds] = useState<string[]>([]);
  const [tz, setTz] = useState("");
  const [bufferMin, setBufferMin] = useState("20");
  const [autoSync, setAutoSync] = useState(true);

  useEffect(() => {
    if (!cfg) return;
    setTargetId(cfg.target_calendar_id || "");
    setBusyIds(cfg.busy_calendar_ids || []);
    setTz(cfg.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Berlin");
    setBufferMin(String(cfg.buffer_minutes ?? 20));
    setAutoSync(cfg.auto_sync ?? true);
  }, [cfg]);

  const saveApp = useMutation({
    mutationFn: () =>
      api("/connections/google-calendar/app", {
        method: "PUT",
        body: { client_id: clientId.trim(), client_secret: clientSecret.trim() },
      }),
    onSuccess: (res) => {
      qc.setQueryData(["gcal-config"], res);
      setClientId("");
      setClientSecret("");
      toast("Saved Google OAuth credentials");
    },
    onError: (e: Error) => toast(e.message, true),
  });

  const saveCfg = useMutation({
    mutationFn: () => {
      const targetCal = calendars?.find((c) => c.id === targetId);
      return api("/connections/google-calendar/config", {
        method: "PUT",
        body: {
          target_calendar_id: targetId || null,
          target_calendar_name: targetCal?.summary || cfg?.target_calendar_name || null,
          busy_calendar_ids: busyIds,
          timezone: tz.trim() || "Europe/Berlin",
          buffer_minutes: Number(bufferMin) || 20,
          auto_sync: autoSync,
        },
      });
    },
    onSuccess: (res) => {
      qc.setQueryData(["gcal-config"], res);
      toast("Saved Google Calendar settings");
    },
    onError: (e: Error) => toast(e.message, true),
  });

  const createCal = useMutation({
    mutationFn: () =>
      api<any>("/connections/google-calendar/calendars", {
        method: "POST",
        body: { name: "RoutePass Training" },
      }),
    onSuccess: (cal) => {
      setTargetId(cal.id);
      qc.invalidateQueries({ queryKey: ["gcal-config"] });
      refetchCals();
      toast(`Created "${cal.summary}" calendar`);
    },
    onError: (e: Error) => toast(e.message, true),
  });

  const disconnect = useMutation({
    mutationFn: () => api("/connections/google-calendar", { method: "DELETE" }),
    onSuccess: (res) => {
      qc.setQueryData(["gcal-config"], res);
      toast("Disconnected Google Calendar");
    },
    onError: (e: Error) => toast(e.message, true),
  });

  const connect = async () => {
    try {
      const r = await api<{ url: string }>("/connections/google-calendar/authorize");
      window.location.assign(r.url);
    } catch (e: any) {
      toast(e.message, true);
    }
  };

  const toggleBusy = (id: string) => {
    setBusyIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  return (
    <Card
      title="Google Calendar"
      hint="Auto-schedules workouts in your dedicated training calendar around busy times from your other calendars"
      actions={
        cfg?.connected ? <span className="badge good">connected</span> : <span className="badge">not connected</span>
      }
    >
      <div className="stack">
        {!cfg?.connected ? (
          <>
            <p className="small muted" style={{ margin: 0 }}>
              Connect your Google account so RoutePass can read busy times across your personal/work calendars and keep
              your dedicated training calendar automatically synced and moved when workouts are adapted.
            </p>
            {cfg?.redirect_uri && (
              <div className="xs muted">
                Authorized redirect URI: <span className="mono">{cfg.redirect_uri}</span>
              </div>
            )}
            <div className="row" style={{ gap: 8 }}>
              <button className="sm primary" disabled={!cfg?.oauth_configured} onClick={connect}>
                Connect Google Calendar
              </button>
              {!cfg?.oauth_configured && (
                <span className="xs muted">Add Google OAuth Client ID & Secret below (or in env vars) first.</span>
              )}
            </div>
            <details open={!cfg?.oauth_configured}>
              <summary className="small secondary" style={{ cursor: "pointer" }}>
                Google OAuth credentials (optional if already set via <span className="mono">ROUTEPASS_GOOGLE_CLIENT_ID</span>)
              </summary>
              <div className="stack mt8">
                <div className="fields">
                  <label className="field">
                    Client ID
                    <input value={clientId} onChange={(e) => setClientId(e.target.value)} />
                  </label>
                  <label className="field">
                    Client Secret
                    <input type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} />
                  </label>
                </div>
                <div className="row">
                  <button
                    className="sm"
                    disabled={!clientId.trim() || !clientSecret.trim() || saveApp.isPending}
                    onClick={() => saveApp.mutate()}
                  >
                    Save OAuth credentials
                  </button>
                </div>
              </div>
            </details>
          </>
        ) : (
          <>
            <div className="row between" style={{ flexWrap: "wrap", gap: 8 }}>
              <span className="small muted">
                Connected · Target: <b>{cfg.target_calendar_name || cfg.target_calendar_id || "Not selected"}</b>
              </span>
              <div className="row" style={{ gap: 6 }}>
                <button className="sm" onClick={() => refetchCals()}>Refresh calendars</button>
                <button className="sm ghost danger" onClick={() => confirm("Disconnect Google Calendar?") && disconnect.mutate()}>
                  Disconnect
                </button>
              </div>
            </div>

            <div className="fields">
              <label className="field">
                Dedicated Training Calendar (writes workout events here)
                <select value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                  <option value="">— Select your training calendar —</option>
                  {(calendars || [])
                    .filter((c) => c.access_role === "owner" || c.access_role === "writer")
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.summary} {c.primary ? "(Primary)" : ""}
                      </option>
                    ))}
                </select>
              </label>
              <div className="field" style={{ justifyContent: "flex-end" }}>
                <button className="sm" disabled={createCal.isPending} onClick={() => createCal.mutate()}>
                  + Create “RoutePass Training” calendar
                </button>
              </div>
            </div>

            {calendars && calendars.length > 0 && (
              <div>
                <div className="xs muted" style={{ marginBottom: 6 }}>
                  Calendars to check for blocked / busy times (read-only):
                </div>
                <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                  {calendars.map((c) => {
                    const checked = busyIds.includes(c.id);
                    return (
                      <label
                        key={c.id}
                        className="row xs"
                        style={{
                          gap: 6,
                          padding: "5px 10px",
                          border: "1px solid var(--border)",
                          borderRadius: 8,
                          cursor: "pointer",
                        }}
                      >
                        <input type="checkbox" checked={checked} onChange={() => toggleBusy(c.id)} />
                        <span>{c.summary}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="fields">
              <label className="field">
                Timezone (IANA)
                <input value={tz} onChange={(e) => setTz(e.target.value)} />
              </label>
              <label className="field">
                Buffer around meetings (minutes)
                <input type="number" min="0" max="120" value={bufferMin} onChange={(e) => setBufferMin(e.target.value)} />
              </label>
            </div>

            <label className="row xs" style={{ gap: 8, cursor: "pointer" }}>
              <input type="checkbox" checked={autoSync} onChange={(e) => setAutoSync(e.target.checked)} />
              <span>Automatically sync & move calendar events after activity sync / AI adaptation</span>
            </label>

            <div className="row">
              <button className="sm primary" disabled={saveCfg.isPending} onClick={() => saveCfg.mutate()}>
                Save Calendar Settings
              </button>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

export function PushNotificationsCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: cfg } = useQuery<any>({
    queryKey: ["push-config"],
    queryFn: () => api("/push/config"),
  });

  const [supported] = useState(
    () => typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window,
  );
  const [subscribing, setSubscribing] = useState(false);
  const [leadMin, setLeadMin] = useState("60");
  const [notifyAdapted, setNotifyAdapted] = useState(true);
  const [notifyCompleted, setNotifyCompleted] = useState(true);
  const [quietStart, setQuietStart] = useState("22");
  const [quietEnd, setQuietEnd] = useState("7");

  useEffect(() => {
    if (!cfg) return;
    setLeadMin(String(cfg.reminder_minutes_before ?? 60));
    setNotifyAdapted(cfg.notify_adapted ?? true);
    setNotifyCompleted(cfg.notify_completed ?? true);
    setQuietStart(String(cfg.quiet_start_hour ?? 22));
    setQuietEnd(String(cfg.quiet_end_hour ?? 7));
  }, [cfg]);

  const saveCfg = useMutation({
    mutationFn: () =>
      api("/push/config", {
        method: "PUT",
        body: {
          reminder_minutes_before: Number(leadMin) || 60,
          notify_adapted: notifyAdapted,
          notify_completed: notifyCompleted,
          quiet_start_hour: Number(quietStart),
          quiet_end_hour: Number(quietEnd),
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Berlin",
        },
      }),
    onSuccess: (res) => {
      qc.setQueryData(["push-config"], res);
      toast("Saved notification preferences");
    },
    onError: (e: Error) => toast(e.message, true),
  });

  const testPush = useMutation({
    mutationFn: () => api<any>("/push/test", { method: "POST" }),
    onSuccess: (r) => {
      if (r.sent > 0) toast("Test notification sent!");
      else toast("No active push subscriptions on this server yet", true);
    },
    onError: (e: Error) => toast(e.message, true),
  });

  const enablePush = async () => {
    if (!supported || !cfg?.vapid_public_key) return;
    setSubscribing(true);
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") {
        toast("Notification permission was denied", true);
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      const existing = await reg.pushManager.getSubscription();
      const sub =
        existing ||
        (await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(cfg.vapid_public_key) as BufferSource,
        }));
      const json = sub.toJSON();
      const updated = await api("/push/subscribe", {
        method: "POST",
        body: { endpoint: json.endpoint, keys: json.keys },
      });
      qc.setQueryData(["push-config"], updated);
      toast("Push notifications enabled on this device");
    } catch (e: any) {
      toast(e.message || "Failed to enable push notifications", true);
    } finally {
      setSubscribing(false);
    }
  };

  return (
    <Card
      title="PWA Notifications & Reminders"
      hint="Receive pre-workout reminders and instant alerts when missed sessions are adapted or moved"
      actions={
        cfg?.subscriptions > 0 ? (
          <span className="badge good">{cfg.subscriptions} device(s) subscribed</span>
        ) : (
          <span className="badge">not enabled</span>
        )
      }
    >
      <div className="stack">
        {!supported && (
          <Callout kind="info">
            Push notifications require a modern browser (on iOS Safari, add RoutePass to your Home Screen first).
          </Callout>
        )}
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <button className="sm primary" disabled={!supported || subscribing} onClick={enablePush}>
            {subscribing ? "Enabling…" : "Enable Push on This Device"}
          </button>
          <button
            className="sm"
            disabled={!cfg?.subscriptions || testPush.isPending}
            onClick={() => testPush.mutate()}
          >
            Send Test Notification
          </button>
        </div>

        <div className="fields">
          <label className="field">
            Pre-workout reminder lead time (minutes)
            <input type="number" min="5" max="1440" value={leadMin} onChange={(e) => setLeadMin(e.target.value)} />
          </label>
          <label className="field">
            Quiet hours start (0–23)
            <input type="number" min="0" max="23" value={quietStart} onChange={(e) => setQuietStart(e.target.value)} />
          </label>
          <label className="field">
            Quiet hours end (0–23)
            <input type="number" min="0" max="23" value={quietEnd} onChange={(e) => setQuietEnd(e.target.value)} />
          </label>
        </div>

        <div className="row" style={{ gap: 16, flexWrap: "wrap" }}>
          <label className="row xs" style={{ gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={notifyAdapted} onChange={(e) => setNotifyAdapted(e.target.checked)} />
            <span>Alert when plan is adapted or session moved</span>
          </label>
          <label className="row xs" style={{ gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={notifyCompleted} onChange={(e) => setNotifyCompleted(e.target.checked)} />
            <span>Alert when synced activity matches a workout</span>
          </label>
        </div>

        <div className="row">
          <button className="sm" disabled={saveCfg.isPending} onClick={() => saveCfg.mutate()}>
            Save Notification Preferences
          </button>
        </div>
      </div>
    </Card>
  );
}
