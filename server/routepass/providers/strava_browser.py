"""Interactive in-app Strava browser sign-in session (Option A).

Launches an ephemeral headless Chromium browser when the user opens the "Sign in to Strava" modal,
streams the live viewport over a WebSocket (CDP screencast + fallback screenshots), forwards the
user's mouse/touch/keyboard input (supporting Email 6-digit One-Time Code, Google, Apple, or
password sign-in), and automatically extracts the HttpOnly `_strava4_session` and
`strava_remember_token` cookies from Chromium's cookie jar as soon as login succeeds.
The Chromium process is terminated immediately after login or modal close (0 MB idle RAM).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import shutil
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from starlette.websockets import WebSocket, WebSocketDisconnect

from routepass.providers import strava

logger = logging.getLogger(__name__)

VIEWPORT_W = 1000
VIEWPORT_H = 680
LOGIN_URL = "https://www.strava.com/login"
SESSION_TIMEOUT_S = 600  # 10 minutes max per interactive login modal session

_session_lock = asyncio.Lock()

_INIT_SCRIPT = """
(() => {
  try {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  } catch (_) {}
  // Keep OAuth popups (Google / Apple sign-in) inside the same tab so the modal view follows them.
  const origOpen = window.open;
  window.open = function(url, target, features) {
    if (url && typeof url === 'string' && !url.startsWith('javascript:')) {
      window.location.assign(url);
      return window;
    }
    return origOpen ? origOpen.call(window, url, target, features) : null;
  };
})();
"""

_AUTO_REMEMBER_JS = """
(() => {
  try {
    const boxes = document.querySelectorAll('input[type="checkbox"][name*="remember"], input#remember_me');
    for (const box of boxes) {
      if (!box.checked) {
        box.checked = true;
        box.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
  } catch (_) {}
})();
"""


def find_chromium_executable() -> str | None:
    """Return a system Chromium/Chrome binary path if installed, or None to use Playwright's cache."""
    env_bin = os.environ.get("ROUTEPASS_CHROMIUM_EXECUTABLE")
    if env_bin and os.path.isfile(env_bin):
        return env_bin
    for candidate in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(candidate)
        if path:
            return path
    return None


def browser_status() -> dict[str, Any]:
    """Check whether Playwright and a Chromium executable are available."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return {"available": False, "reason": "playwright package is not installed"}
    exe = find_chromium_executable()
    return {"available": True, "executable": exe or "playwright-bundled"}


def _is_authenticated_strava_url(url: str) -> bool:
    """True when the browser has navigated past /login and /session onto an authenticated Strava page."""
    if not url:
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not (host == "strava.com" or host.endswith(".strava.com")):
        return False
    path = parsed.path.rstrip("/") or "/"
    unauth_prefixes = (
        "/login",
        "/session",
        "/register",
        "/account/recover",
        "/oauth",
    )
    return not any(path == p or path.startswith(p + "/") for p in unauth_prefixes)


def _verify_cookies_sync(cookies: dict[str, str]) -> tuple[dict[str, Any], dict[str, str]] | None:
    """Verify captured cookies with StravaWebClient in a worker thread."""
    if not cookies.get("_strava4_session") and not cookies.get("strava_remember_token"):
        return None
    try:
        with strava.StravaWebClient(cookies) as client:
            athlete = client.athlete()
            return athlete, dict(client.cookies)
    except Exception:  # noqa: BLE001
        return None


async def run_browser_login_session(
    websocket: WebSocket,
    on_authenticated: Callable[[dict[str, str], dict[str, Any]], None],
) -> None:
    """Run an interactive Strava sign-in browser streamed over `websocket`."""
    await websocket.accept()

    if _session_lock.locked():
        await websocket.send_json(
            {
                "type": "error",
                "message": "Another Strava sign-in session is already open. Close it or wait a moment.",
            }
        )
        await websocket.close(code=1008)
        return

    async with _session_lock:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            await websocket.send_json(
                {"type": "error", "message": "Playwright is not installed on this server."}
            )
            await websocket.close(code=1011)
            return

        await websocket.send_json(
            {
                "type": "status",
                "message": "Starting secure Strava browser session…",
                "viewport": {"width": VIEWPORT_W, "height": VIEWPORT_H},
            }
        )

        pw = None
        browser = None
        context = None
        stop_event = asyncio.Event()
        last_frame_at = 0.0

        async def send_safe(payload: dict[str, Any]) -> bool:
            if stop_event.is_set():
                return False
            try:
                await websocket.send_json(payload)
                return True
            except Exception:  # noqa: BLE001
                stop_event.set()
                return False

        try:
            pw = await async_playwright().start()
            exe = find_chromium_executable()
            launch_kwargs: dict[str, Any] = {
                "headless": True,
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu",
                    f"--window-size={VIEWPORT_W},{VIEWPORT_H}",
                ],
            }
            if exe:
                try:
                    browser = await pw.chromium.launch(executable_path=exe, **launch_kwargs)
                except Exception:  # noqa: BLE001
                    browser = await pw.chromium.launch(**launch_kwargs)
            else:
                browser = await pw.chromium.launch(**launch_kwargs)

            context = await browser.new_context(
                viewport={"width": VIEWPORT_W, "height": VIEWPORT_H},
                user_agent=strava.WEB_UA,
                locale="en-US",
            )
            await context.add_init_script(_INIT_SCRIPT)
            page = await context.new_page()

            # Redirect any popup tabs (e.g. Google/Apple OAuth popup) into the main page.
            def _on_popup(popup) -> None:
                async def _redirect_popup() -> None:
                    with contextlib.suppress(Exception):
                        await popup.wait_for_load_state("domcontentloaded", timeout=5000)
                        popup_url = popup.url
                        await popup.close()
                        if popup_url and popup_url != "about:blank":
                            await page.goto(popup_url, wait_until="domcontentloaded")

                asyncio.create_task(_redirect_popup())

            context.on("page", _on_popup)

            # Set up CDP Screencast for smooth real-time visual updates.
            cdp = None
            with contextlib.suppress(Exception):
                cdp = await context.new_cdp_session(page)

                def _on_screencast_frame(params: dict[str, Any]) -> None:
                    nonlocal last_frame_at
                    last_frame_at = time.monotonic()
                    session_id = params.get("sessionId")
                    data = params.get("data")

                    async def _ack_and_forward() -> None:
                        if cdp is not None and session_id is not None:
                            with contextlib.suppress(Exception):
                                await cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
                        if data:
                            await send_safe(
                                {
                                    "type": "frame",
                                    "data": data,
                                    "url": page.url,
                                }
                            )

                    asyncio.create_task(_ack_and_forward())

                cdp.on("Page.screencastFrame", _on_screencast_frame)
                await cdp.send(
                    "Page.startScreencast",
                    {
                        "format": "jpeg",
                        "quality": 78,
                        "maxWidth": VIEWPORT_W,
                        "maxHeight": VIEWPORT_H,
                        "everyNthFrame": 1,
                    },
                )

            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            with contextlib.suppress(Exception):
                await page.evaluate(_AUTO_REMEMBER_JS)

            async def capture_snapshot() -> None:
                nonlocal last_frame_at
                if stop_event.is_set():
                    return
                with contextlib.suppress(Exception):
                    raw = await page.screenshot(type="jpeg", quality=75)
                    last_frame_at = time.monotonic()
                    await send_safe(
                        {
                            "type": "frame",
                            "data": base64.b64encode(raw).decode("ascii"),
                            "url": page.url,
                        }
                    )

            await capture_snapshot()

            async def frame_and_cookie_watcher() -> None:
                started = time.monotonic()
                last_verified_session: str | None = None
                while not stop_event.is_set():
                    if time.monotonic() - started > SESSION_TIMEOUT_S:
                        await send_safe(
                            {"type": "error", "message": "Sign-in session timed out after 10 minutes."}
                        )
                        stop_event.set()
                        break

                    with contextlib.suppress(Exception):
                        if "/login" in page.url:
                            await page.evaluate(_AUTO_REMEMBER_JS)

                    # Fallback frame push if CDP screencast hasn't emitted a frame recently.
                    if time.monotonic() - last_frame_at > 0.9:
                        await capture_snapshot()

                    # Check Chromium cookie jar for authenticated Strava cookies.
                    with contextlib.suppress(Exception):
                        jar = await context.cookies(["https://www.strava.com", "https://strava.com"])
                        cookie_map = {c["name"]: c["value"] for c in jar if c.get("name") and c.get("value")}
                        sess_val = cookie_map.get("_strava4_session")
                        has_remember = bool(cookie_map.get("strava_remember_token"))
                        if sess_val and (
                            _is_authenticated_strava_url(page.url)
                            or (has_remember and sess_val != last_verified_session)
                        ):
                            last_verified_session = sess_val
                            verified = await asyncio.to_thread(_verify_cookies_sync, cookie_map)
                            if verified is not None:
                                athlete, final_cookies = verified
                                await asyncio.to_thread(on_authenticated, final_cookies, athlete)
                                await send_safe(
                                    {
                                        "type": "connected",
                                        "athlete": athlete,
                                        "has_remember_token": "strava_remember_token" in final_cookies,
                                    }
                                )
                                stop_event.set()
                                break

                    await asyncio.sleep(0.65)

            async def input_loop() -> None:
                while not stop_event.is_set():
                    try:
                        msg = await websocket.receive_json()
                    except WebSocketDisconnect:
                        stop_event.set()
                        break
                    except Exception:  # noqa: BLE001
                        stop_event.set()
                        break

                    kind = msg.get("type")
                    with contextlib.suppress(Exception):
                        if kind == "click":
                            x = max(0, min(VIEWPORT_W, float(msg.get("x", 0))))
                            y = max(0, min(VIEWPORT_H, float(msg.get("y", 0))))
                            await page.mouse.click(x, y)
                            await asyncio.sleep(0.12)
                            await capture_snapshot()
                        elif kind == "mousedown":
                            x = max(0, min(VIEWPORT_W, float(msg.get("x", 0))))
                            y = max(0, min(VIEWPORT_H, float(msg.get("y", 0))))
                            await page.mouse.move(x, y)
                            await page.mouse.down()
                        elif kind == "mouseup":
                            x = max(0, min(VIEWPORT_W, float(msg.get("x", 0))))
                            y = max(0, min(VIEWPORT_H, float(msg.get("y", 0))))
                            await page.mouse.move(x, y)
                            await page.mouse.up()
                            await asyncio.sleep(0.1)
                            await capture_snapshot()
                        elif kind == "mousemove":
                            x = max(0, min(VIEWPORT_W, float(msg.get("x", 0))))
                            y = max(0, min(VIEWPORT_H, float(msg.get("y", 0))))
                            await page.mouse.move(x, y)
                        elif kind == "wheel":
                            dx = float(msg.get("deltaX", 0))
                            dy = float(msg.get("deltaY", 0))
                            await page.mouse.wheel(dx, dy)
                            await asyncio.sleep(0.08)
                            await capture_snapshot()
                        elif kind == "key":
                            key = str(msg.get("key") or "")
                            if key:
                                if len(key) == 1:
                                    await page.keyboard.insert_text(key)
                                else:
                                    await page.keyboard.press(key)
                                await asyncio.sleep(0.08)
                                await capture_snapshot()
                        elif kind == "text":
                            text = str(msg.get("text") or "")
                            if text:
                                await page.keyboard.insert_text(text)
                                if msg.get("submit"):
                                    await page.keyboard.press("Enter")
                                await asyncio.sleep(0.12)
                                await capture_snapshot()
                        elif kind == "navigate":
                            action = msg.get("action")
                            if action == "reload":
                                await page.reload(wait_until="domcontentloaded")
                            elif action == "back":
                                await page.go_back(wait_until="domcontentloaded")
                            elif action == "reset":
                                await page.goto(LOGIN_URL, wait_until="domcontentloaded")
                            await asyncio.sleep(0.15)
                            await capture_snapshot()

            watcher_task = asyncio.create_task(frame_and_cookie_watcher())
            input_task = asyncio.create_task(input_loop())
            await asyncio.wait(
                [watcher_task, input_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            stop_event.set()
            for t in (watcher_task, input_task):
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
        except Exception as exc:  # noqa: BLE001
            logger.exception("Strava interactive browser login error")
            with contextlib.suppress(Exception):
                await websocket.send_json({"type": "error", "message": str(exc)[:300]})
        finally:
            stop_event.set()
            with contextlib.suppress(Exception):
                if context is not None:
                    await context.close()
            with contextlib.suppress(Exception):
                if browser is not None:
                    await browser.close()
            with contextlib.suppress(Exception):
                if pw is not None:
                    await pw.stop()
            with contextlib.suppress(Exception):
                await websocket.close()
