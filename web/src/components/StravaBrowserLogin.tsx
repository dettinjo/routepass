import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { BrandIcon, IconCheck, IconRefresh } from "./icons";
import { Callout, Modal, useToast } from "./ui";

export function StravaBrowserLoginModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const wsRef = useRef<WebSocket | null>(null);
  const viewRef = useRef<HTMLDivElement | null>(null);

  const [frame, setFrame] = useState<string | null>(null);
  const [currentUrl, setCurrentUrl] = useState<string>("https://www.strava.com/login");
  const [statusMsg, setStatusMsg] = useState<string>("Starting Strava sign-in browser…");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [connectedAthlete, setConnectedAthlete] = useState<{ id?: number | string; name?: string } | null>(null);
  const [viewport, setViewport] = useState<{ width: number; height: number }>({ width: 1000, height: 680 });
  const [quickText, setQuickText] = useState<string>("");

  const send = (payload: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  };

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/api/v1/connections/strava/browser-login`);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "status") {
          setStatusMsg(msg.message || "Loading Strava…");
          if (msg.viewport) setViewport(msg.viewport);
        } else if (msg.type === "frame") {
          setFrame(msg.data);
          if (msg.url) setCurrentUrl(msg.url);
          setErrorMsg(null);
        } else if (msg.type === "error") {
          setErrorMsg(msg.message || "Strava browser session failed");
        } else if (msg.type === "connected") {
          setConnectedAthlete(msg.athlete || {});
          qc.invalidateQueries({ queryKey: ["status"] });
          toast(`Strava connected as ${msg.athlete?.name || "athlete"} (auto-updating session)`);
          window.setTimeout(() => onClose(), 1200);
        }
      } catch {
        /* ignore malformed frame */
      }
    };

    ws.onerror = () => {
      setErrorMsg("Connection to the sign-in browser was interrupted.");
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [onClose, qc, toast]);

  const toViewportCoords = (clientX: number, clientY: number, el: HTMLElement) => {
    const rect = el.getBoundingClientRect();
    const x = Math.round(((clientX - rect.left) / Math.max(1, rect.width)) * viewport.width);
    const y = Math.round(((clientY - rect.top) / Math.max(1, rect.height)) * viewport.height);
    return { x, y };
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    // Allow Cmd/Ctrl+V paste event to fire naturally
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "v") return;
    if (e.key === "Escape") return;
    e.preventDefault();
    e.stopPropagation();
    send({ type: "key", key: e.key });
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLDivElement>) => {
    const pasted = e.clipboardData.getData("text");
    if (pasted) {
      e.preventDefault();
      send({ type: "text", text: pasted });
    }
  };

  const sendQuickText = (submit: boolean) => {
    if (!quickText) {
      if (submit) send({ type: "key", key: "Enter" });
      return;
    }
    send({ type: "text", text: quickText, submit });
    setQuickText("");
    viewRef.current?.focus();
  };

  return (
    <Modal
      title={
        <span className="row nowrap" style={{ gap: 8 }}>
          <BrandIcon provider="strava" size={20} />
          Sign in to Strava
        </span>
      }
      onClose={onClose}
      footer={
        <div className="row between" style={{ width: "100%" }}>
          <span className="xs muted">
            Cookies (<span className="mono">_strava4_session</span> + <span className="mono">strava_remember_token</span>) are captured & refreshed automatically.
          </span>
          <button onClick={onClose}>Close</button>
        </div>
      }
    >
      <div className="stack" style={{ gap: 10 }}>
        {connectedAthlete ? (
          <Callout kind="good">
            <b>Connected to Strava as {connectedAthlete.name || `Athlete ${connectedAthlete.id}`}!</b>
            <div className="xs muted">Your session cookie and remember-me token were saved and will renew automatically.</div>
          </Callout>
        ) : (
          <p className="small muted" style={{ margin: 0 }}>
            Click any field below to type directly, or use the quick input bar (great for mobile & pasting the <b>6-digit Email One-Time Code</b>). Works with <b>Email One-Time Code</b>, <b>Google</b>, <b>Apple</b>, or password.
          </p>
        )}

        {errorMsg && <Callout kind="bad">{errorMsg}</Callout>}

        {/* Browser navigation & quick-type bar */}
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
          <button type="button" className="sm" onClick={() => send({ type: "navigate", action: "back" })} title="Back">
            ← Back
          </button>
          <button type="button" className="sm" onClick={() => send({ type: "navigate", action: "reload" })} title="Reload page">
            <IconRefresh size={14} /> Reload
          </button>
          <button type="button" className="sm ghost" onClick={() => send({ type: "navigate", action: "reset" })} title="Back to strava.com/login">
            Reset to Login
          </button>
          <span className="xs mono muted ellipsis" style={{ flex: 1, minWidth: 160, padding: "4px 8px", background: "var(--bg-muted, rgba(128,128,128,0.1))", borderRadius: 6 }}>
            {currentUrl}
          </span>
        </div>

        <form
          className="row"
          style={{ gap: 6, flexWrap: "nowrap" }}
          onSubmit={(e) => {
            e.preventDefault();
            sendQuickText(true);
          }}
        >
          <input
            placeholder="Click a field on Strava below, then type or paste email / 6-digit code / password here…"
            value={quickText}
            onChange={(e) => setQuickText(e.target.value)}
            style={{ flex: 1 }}
          />
          <button type="button" className="sm" onClick={() => sendQuickText(false)} disabled={!quickText}>
            Type
          </button>
          <button type="submit" className="primary sm">
            {quickText ? "Type + Enter" : "Press Enter"}
          </button>
          <button type="button" className="sm ghost" onClick={() => send({ type: "key", key: "Tab" })} title="Move to next field">
            Tab ⇥
          </button>
        </form>

        {/* Interactive streamed browser viewport */}
        <div
          ref={viewRef}
          tabIndex={0}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          onWheel={(e) => {
            send({ type: "wheel", deltaX: e.deltaX, deltaY: e.deltaY });
          }}
          style={{
            position: "relative",
            width: "100%",
            aspectRatio: `${viewport.width} / ${viewport.height}`,
            background: "#111",
            borderRadius: 10,
            overflow: "hidden",
            border: "2px solid var(--border)",
            outline: "none",
            cursor: "pointer",
            userSelect: "none",
          }}
        >
          {frame ? (
            <img
              src={`data:image/jpeg;base64,${frame}`}
              alt="Strava sign-in browser"
              draggable={false}
              onClick={(e) => {
                viewRef.current?.focus();
                const { x, y } = toViewportCoords(e.clientX, e.clientY, e.currentTarget);
                send({ type: "click", x, y });
              }}
              style={{ width: "100%", height: "100%", display: "block", objectFit: "contain" }}
            />
          ) : (
            <div
              className="stack"
              style={{
                height: "100%",
                alignItems: "center",
                justifyContent: "center",
                color: "#ccc",
                padding: 24,
                textAlign: "center",
              }}
            >
              <IconRefresh size={26} className="spin" />
              <div className="small">{statusMsg}</div>
            </div>
          )}
          {connectedAthlete && (
            <div
              style={{
                position: "absolute",
                inset: 0,
                background: "rgba(0,0,0,0.65)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#fff",
                fontWeight: 600,
                gap: 8,
              }}
            >
              <IconCheck size={24} /> Strava Connected!
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
