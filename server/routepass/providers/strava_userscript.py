"""Generate a lightweight 1-click Userscript (Tampermonkey / Violentmonkey / Safari Userscripts).

The userscript runs on https://www.strava.com/* in the user's own browser, reads the HttpOnly
`_strava4_session` and `strava_remember_token` cookies via `GM_cookie.list`, and sends them
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
// @version      1.0.0
// @description  Automatically syncs your Strava session cookies (_strava4_session + strava_remember_token) to RoutePass when you sign in on strava.com.
// @match        https://www.strava.com/*
// @grant        GM_cookie
// @grant        GM_xmlhttpRequest
// @connect      {host}
// @run-at       document-idle
// ==/UserScript==

(function () {{
  "use strict";

  const ROUTEPASS_URL = {origin_js};
  const HANDOFF_TOKEN = {token_js};
  const CONNECT_KEY = "routepass_connect_pending";
  const FP_KEY = "routepass_cookie_fp";

  const path = window.location.pathname || "/";
  const isLoginPage = /^\\/(login|session|register)(\\/|$)/.test(path);

  if (window.location.hash === "#routepass-connect") {{
    try {{
      sessionStorage.setItem(CONNECT_KEY, "1");
    }} catch (_) {{}}
  }}

  const pendingConnect = (() => {{
    try {{
      return sessionStorage.getItem(CONNECT_KEY) === "1" || window.location.hash === "#routepass-connect";
    }} catch (_) {{
      return window.location.hash === "#routepass-connect";
    }}
  }})();

  function showToast(text, bg) {{
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
        maxWidth: "340px",
      }});
      document.body.appendChild(el);
    }}
    el.style.background = bg || "#fc4c02";
    el.textContent = text;
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
    if (pendingConnect) {{
      showToast("RoutePass: Sign in to Strava to connect automatically", "#fc4c02");
    }}
    return;
  }}

  function readStravaCookies(cb) {{
    if (typeof GM_cookie === "undefined" || typeof GM_cookie.list !== "function") {{
      if (pendingConnect) {{
        showToast("RoutePass: Your userscript manager must support GM_cookie (use Tampermonkey 5+).", "#b91c1c");
      }}
      return;
    }}
    GM_cookie.list({{ domain: "strava.com" }}, (cookies, error) => {{
      if (error || !Array.isArray(cookies)) {{
        if (pendingConnect) {{
          showToast("RoutePass: Could not read Strava cookies (" + (error || "unknown") + ")", "#b91c1c");
        }}
        return;
      }}
      const map = {{}};
      for (const c of cookies) {{
        if (c && c.name && c.value) {{
          map[c.name] = c.value;
        }}
      }}
      if (!map._strava4_session && !map.strava_remember_token) {{
        return;
      }}
      cb(map);
    }});
  }}

  function syncCookies(cookies) {{
    const fp = (cookies._strava4_session || "") + "|" + (cookies.strava_remember_token || "");
    let prev = "";
    try {{
      prev = localStorage.getItem(FP_KEY) || "";
    }} catch (_) {{}}

    if (!pendingConnect && fp === prev) {{
      return; // Already up to date
    }}

    if (pendingConnect) {{
      showToast("RoutePass: Connecting Strava session…", "#2563eb");
    }}

    GM_xmlhttpRequest({{
      method: "POST",
      url: ROUTEPASS_URL + "/api/v1/connections/strava/session/handoff",
      headers: {{ "Content-Type": "application/json" }},
      data: JSON.stringify({{
        token: HANDOFF_TOKEN,
        cookies: cookies,
      }}),
      onload: (resp) => {{
        if (resp.status >= 200 && resp.status < 300) {{
          try {{
            localStorage.setItem(FP_KEY, fp);
            sessionStorage.removeItem(CONNECT_KEY);
          }} catch (_) {{}}
          if (pendingConnect) {{
            showToast("RoutePass: Strava connected! Returning to RoutePass…", "#15803d");
            setTimeout(() => {{
              window.location.href = ROUTEPASS_URL + "/settings?strava=connected";
            }}, 600);
          }}
        }} else if (pendingConnect) {{
          showToast("RoutePass: Connection failed (HTTP " + resp.status + ")", "#b91c1c");
        }}
      }},
      onerror: () => {{
        if (pendingConnect) {{
          showToast("RoutePass: Could not reach " + ROUTEPASS_URL, "#b91c1c");
        }}
      }},
    }});
  }}

  readStravaCookies(syncCookies);
}})();
"""
