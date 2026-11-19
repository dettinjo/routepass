import { useState } from "react";
import { Logo } from "../components/Logo";
import { ICON, IconKey } from "../components/icons";
import { Callout } from "../components/ui";
import type { Me } from "../lib/api";

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}

export default function Login({ me }: { me: Me | null }) {
  const params = new URLSearchParams(window.location.search);
  const [error, setError] = useState(params.get("error"));
  const [showToken, setShowToken] = useState(!me?.methods.google);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);

  const tokenLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const res = await fetch("/api/v1/auth/token-login", {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }),
    });
    setBusy(false);
    if (res.ok) window.location.replace("/");
    else setError("That access token is not right.");
  };

  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 16 }}>
      <div className="card stack gap16" style={{ width: "min(400px, 100%)", padding: 24 }}>
        <div className="stack" style={{ alignItems: "center", gap: 10, textAlign: "center" }}>
          <Logo size={56} />
          <h1>RoutePass</h1>
          <p className="secondary small">Your Strava and Komoot activities, in one place.</p>
        </div>
        {error && <Callout kind="bad">{error}</Callout>}
        {me?.methods.google && (
          <a className="btn block" href="/api/v1/auth/google/start" style={{ minHeight: 46, fontSize: 15, width: "100%" }}>
            <GoogleMark />Sign in with Google
          </a>
        )}
        {me?.methods.tailscale && (
          <p className="xs muted" style={{ textAlign: "center" }}>
            On your own devices connected to Tailscale you are signed in automatically.
          </p>
        )}
        {me?.methods.token && (
          showToken ? (
            <form className="stack" onSubmit={tokenLogin}>
              <label className="field">Access token
                <input type="password" autoComplete="current-password" value={token} onChange={(e) => setToken(e.target.value)} autoFocus={!me?.methods.google} />
              </label>
              <button className="primary" type="submit" disabled={!token || busy}><IconKey size={ICON.button} />Sign in</button>
            </form>
          ) : (
            <button className="ghost sm" onClick={() => setShowToken(true)}><IconKey size={ICON.button} />Use the access token instead</button>
          )
        )}
      </div>
    </div>
  );
}
