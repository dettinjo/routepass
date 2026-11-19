"""Generate a lightweight 1-click Userscript (Tampermonkey BETA / Violentmonkey / Safari Userscripts).

The userscript runs on https://www.strava.com/* in the user's own browser, reads the HttpOnly
`_strava4_session` and `strava_remember_token` cookies via `GM_cookie.list({})`, and sends them
to RoutePass using a scoped HMAC handoff token (valid only for `/connections/strava/session/handoff`).
Zero extra Docker dependencies (0 MB overhead).
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlparse

from routepass import auth

HANDOFF_PURPOSE = "strava_session_sync"
HANDOFF_TTL_S = 365 * 86400  # 1 year


def issue_handoff_token() -> str:
    now = int(time.time())
    return auth.sign({"purpose": HANDOFF_PURPOSE, "iat": now, "exp": now + HANDOFF_TTL_S})


def verify_handoff_token(token: str | None) -> bool:
    payload = auth.unsign(token)
    return bool(payload and payload.get("purpose") == HANDOFF_PURPOSE)


def render_userscript(base_url: str, token: str) -> str:
    """Return the complete `.user.js` source code configured for `base_url`."""
    origin = base_url.rstrip("/")
    host = urlparse(origin).hostname or "*"
    origin_js = json.dumps(origin)
    token_js = json.dumps(token)
    return f"""// ==UserScript==
// @name         RoutePass Strava Auto-Connect
// @namespace    {origin}/
// @version      1.2.0
// @description  Automatically syncs your Strava session cookies (_strava4_session + strava_remember_token) to RoutePass when you sign in on strava.com.
// @match        https://www.strava.com/*
// @grant        GM_cookie
// @grant        GM_xmlhttpRequest
// @grant        GM_registerMenuCommand
// @connect      {host}
// @run-at       document-idle
// ==/UserScript==

(function () {{
  "use strict";

  const ROUTEPASS_URL = {origin_js};
  const HANDOFF_TOKEN = {token_js};
  const CONNECT_UNTIL_KEY = "routepass_connect_until";
  const FP_KEY = "routepass_cookie_fp";

  const path = window.location.pathname || "/";
  const isLoginPage = /^\\/(login|session|register)(\\/|$)/.test(path);

  if (
    window.location.hash === "#routepass-connect" ||
    window.location.search.includes("routepass_connect=1")
  ) {{
    try {{
      // Persist for 15 minutes in localStorage so it survives Google/Apple OAuth redirects.
      localStorage.setItem(CONNECT_UNTIL_KEY, String(Date.now() + 15 * 60 * 1000));
    }} catch (_) {{}}
  }}

  function isPendingConnect() {{
    if (window.location.hash === "#routepass-connect") return true;
    try {{
      const until = Number(localStorage.getItem(CONNECT_UNTIL_KEY) || "0");
      return until > Date.now();
    }} catch (_) {{
      return false;
    }}
  }}

  function clearPendingConnect() {{
    try {{
      localStorage.removeItem(CONNECT_UNTIL_KEY);
    }} catch (_) {{}}
  }}

  function showToast(text, bg, persistMs) {{
    console.info("[RoutePass]", text);
    let el = document.getElementById("rp-strava-toast");
    if (!el) {{
      el = document.createElement("div");
      el.id = "rp-strava-toast";
      Object.assign(el.style, {{
        position: "fixed",
        right: "16px",
        bottom: "16px",
        zIndex: "2147483647",
        padding: "10px 14px",
        borderRadius: "10px",
        color: "#fff",
        fontFamily: "system-ui, -apple-system, sans-serif",
        fontSize: "13px",
        fontWeight: "600",
        boxShadow: "0 6px 20px rgba(0,0,0,0.28)",
        maxWidth: "380px",
        lineHeight: "1.35",
      }});
      document.body.appendChild(el);
    }}
    el.style.background = bg || "#fc4c02";
    el.textContent = text;
    if (persistMs) {{
      setTimeout(() => {{
        if (el && el.parentNode) el.parentNode.removeChild(el);
      }}, persistMs);
    }}
  }}

  // On /login, automatically tick "Remember me" so Strava issues strava_remember_token.
  if (isLoginPage) {{
    const tickRemember = () => {{
      document
        .querySelectorAll('input[type="checkbox"][name*="remember"], input#remember_me')
        .forEach((box) => {{
          if (!box.checked) {{
            box.checked = true;
            box.dispatchEvent(new Event("change", {{ bubbles: true }}));
          }}
        }});
    }};
    tickRemember();
    setTimeout(tickRemember, 800);
    if (isPendingConnect()) {{
      showToast("RoutePass: Sign in to Strava to connect automatically", "#fc4c02");
    }}
    return;
  }}

  function queryCookies(filter) {{
    return new Promise((resolve) => {{
      try {{
        GM_cookie.list(filter, (cookies, error) => {{
          if (error || !Array.isArray(cookies)) return resolve([]);
          resolve(cookies);
        }});
      }} catch (_) {{
        resolve([]);
      }}
    }});
  }}

  async function readStravaCookies(force, cb) {{
    if (typeof GM_cookie === "undefined" || typeof GM_cookie.list !== "function") {{
      showToast(
        "RoutePass: GM_cookie is unavailable. On Chrome/Edge install Tampermonkey BETA (not Stable) so HttpOnly cookies can be read.",
        "#b91c1c"
      );
      return;
    }}
    // Query url, .strava.com, and explicit names so both host-only and domain cookies are captured.
    const batches = await Promise.all([
      queryCookies({{ url: "https://www.strava.com/" }}),
      queryCookies({{ domain: ".strava.com" }}),
      queryCookies({{ name: "_strava4_session" }}),
      queryCookies({{ name: "strava_remember_token" }}),
    ]);
    const map = {{}};
    for (const list of batches) {{
      for (const c of list) {{
        if (c && c.name && c.value) {{
          map[c.name] = c.value;
        }}
      }}
    }}
    const keys = Object.keys(map);
    console.info("[RoutePass] Found cookies:", keys);
    if (!map._strava4_session && !map.strava_remember_token) {{
      if (force) {{
        const sample = keys.slice(0, 6).join(", ") || "none";
        showToast(
          "RoutePass: _strava4_session not visible (saw: " +
            sample +
            "). Note: Tampermonkey Stable hides HttpOnly cookies — use Tampermonkey BETA or paste Copy as cURL in Settings.",
          "#b91c1c"
        );
      }}
      return;
    }}
    cb(map);
  }}

  function syncCookies(cookies, force) {{
    const fp = (cookies._strava4_session || "") + "|" + (cookies.strava_remember_token || "");
    let prev = "";
    try {{
      prev = localStorage.getItem(FP_KEY) || "";
    }} catch (_) {{}}

    if (!force && fp === prev) {{
      return; // Already up to date
    }}

    if (force) {{
      showToast("RoutePass: Sending Strava session to " + ROUTEPASS_URL + "…", "#2563eb");
    }}

    GM_xmlhttpRequest({{
      method: "POST",
      url: ROUTEPASS_URL + "/api/v1/connections/strava/session/handoff",
      headers: {{
        "Content-Type": "application/json",
        Authorization: "Bearer " + HANDOFF_TOKEN,
      }},
      data: JSON.stringify({{
        token: HANDOFF_TOKEN,
        cookies: cookies,
      }}),
      onload: (resp) => {{
        if (resp.status >= 200 && resp.status < 300) {{
          try {{
            localStorage.setItem(FP_KEY, fp);
          }} catch (_) {{}}
          clearPendingConnect();
          if (force) {{
            showToast("RoutePass: Strava connected! Returning to RoutePass…", "#15803d");
            setTimeout(() => {{
              window.location.href = ROUTEPASS_URL + "/settings?strava=connected";
            }}, 700);
          }}
        }} else {{
          let detail = "";
          try {{
            const parsed = JSON.parse(resp.responseText || "{{}}");
            detail = parsed.detail ? " — " + parsed.detail : "";
          }} catch (_) {{
            detail = resp.responseText ? " — " + resp.responseText.slice(0, 120) : "";
          }}
          showToast("RoutePass: Failed (HTTP " + resp.status + ")" + detail, "#b91c1c");
        }}
      }},
      onerror: (err) => {{
        console.error("[RoutePass] GM_xmlhttpRequest error", err);
        showToast(
          "RoutePass: Could not reach " + ROUTEPASS_URL + " (check Tailscale / HTTPS & allow @connect in Tampermonkey)",
          "#b91c1c"
        );
      }},
    }});
  }}

  function runSync(force) {{
    readStravaCookies(force, (cookies) => syncCookies(cookies, force));
  }}

  if (typeof GM_registerMenuCommand === "function") {{
    GM_registerMenuCommand("Connect Strava to RoutePass now", () => runSync(true));
  }}

  runSync(isPendingConnect());
}})();
"""
