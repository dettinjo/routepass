"""Cost-aware Gemini client for RoutePass adaptive training plans.

Supports both:
- Google Cloud Vertex AI Express / API keys (`AQ....`) via aiplatform.googleapis.com
- Google AI Studio API keys (`AIza...`) via generativelanguage.googleapis.com

Enforces a monthly USD budget cap tracked in `ai_usage_log` (thinking tokens count as output).
Requests run from the AI coach's background worker (routepass.ai.coach), never inside a request
handler or an open database transaction: gemini-4 models can take a minute to answer.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from routepass import store
from routepass.config import get_settings
from routepass.models import AIUsageLog
from routepass.timeutil import utcnow

logger = logging.getLogger(__name__)

# Approximate USD per 1M tokens (input, output) for cost accounting
MODEL_PRICING_USD_PER_M: dict[str, tuple[float, float]] = {
    "gemini-4-hydrogen": (1.50, 7.50),
    "gemini-4-argon": (2.00, 10.00),
    "gemini-4-carbon": (4.00, 20.00),
    "gemini-3.8-flash": (1.50, 7.50),
    "gemini-3.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash-lite": (0.075, 0.30),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 10.00),
}

AVAILABLE_MODELS: list[dict[str, Any]] = [
    {
        "id": "gemini-4-hydrogen",
        "label": "Gemini 4 Hydrogen (Recommended · Fast & efficient)",
        "input_usd_per_m": 1.50,
        "output_usd_per_m": 7.50,
    },
    {
        "id": "gemini-4-argon",
        "label": "Gemini 4 Argon (Frontier reasoning)",
        "input_usd_per_m": 2.00,
        "output_usd_per_m": 10.00,
    },
    {
        "id": "gemini-4-carbon",
        "label": "Gemini 4 Carbon (Flagship reasoning)",
        "input_usd_per_m": 4.00,
        "output_usd_per_m": 20.00,
    },
    {
        "id": "gemini-3.8-flash",
        "label": "Gemini 3.8 Flash (Previous fast)",
        "input_usd_per_m": 1.50,
        "output_usd_per_m": 7.50,
    },
    {
        "id": "gemini-3.5-flash-lite",
        "label": "Gemini 3.5 Flash-Lite (Ultra low-cost)",
        "input_usd_per_m": 0.10,
        "output_usd_per_m": 0.40,
    },
]

_SECRET_KEY = "gemini.credentials"
_CONFIG_KEY = "gemini.config"
_STATUS_KEY = "gemini.status"  # last call: ok or error, when, how long


class GeminiError(RuntimeError):
    """Base error for Gemini calls."""


class GeminiNotConfiguredError(GeminiError):
    """Raised when no Gemini API key is configured."""


class BudgetExceededError(GeminiError):
    """Raised when the monthly Gemini USD budget cap has been reached."""


class QuotaPausedError(GeminiError):
    """Google's quota for the key is used up (e.g. the free tier's requests per day): no calls until
    `until` (UTC ISO), which Google tells us."""

    def __init__(self, message: str, until: str):
        super().__init__(message)
        self.until = until


def _quota_pause(resp: httpx.Response) -> tuple[str, float] | None:
    """For a 429 that retrying won't fix (a daily quota): (message, seconds until it resets)."""
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        return None
    delay, daily, msg = 0.0, False, err.get("message") or "quota exceeded"
    for d in err.get("details") or []:
        if d.get("@type", "").endswith("QuotaFailure"):
            for v in d.get("violations") or []:
                daily = daily or "PerDay" in (v.get("quotaId") or "")
                if v.get("description"):
                    msg = v["description"]
                    if v.get("quotaValue"):
                        msg += f" (limit {v['quotaValue']})"
        if d.get("@type", "").endswith("RetryInfo"):
            try:
                delay = float(str(d.get("retryDelay", "0")).rstrip("s"))
            except ValueError:
                delay = 0.0
    if daily or delay > 300:
        return msg, max(delay, 600.0)
    return None


def get_api_key(db: Session) -> str:
    """Return configured Gemini API key (encrypted DB secret takes precedence over env var)."""
    secret = store.get_secret(db, _SECRET_KEY)
    if secret and secret.get("api_key"):
        return str(secret["api_key"]).strip()
    return get_settings().gemini_api_key.strip()


def get_ai_config(db: Session) -> dict[str, Any]:
    """Return non-secret Gemini configuration and current month usage."""
    settings = get_settings()
    cfg = store.get_value(db, _CONFIG_KEY) or {}
    secret = store.get_secret(db, _SECRET_KEY)
    has_db_key = bool(secret and secret.get("api_key"))
    has_env_key = bool(settings.gemini_api_key.strip())
    budget = float(cfg.get("monthly_budget_usd", settings.gemini_monthly_budget_usd))
    model_fast = str(cfg.get("model_fast") or settings.gemini_model_fast)
    model_pro = str(cfg.get("model_pro") or settings.gemini_model_pro)
    usage = monthly_usage(db)
    return {
        "configured": has_db_key or has_env_key,
        "key_source": "settings" if has_db_key else ("env" if has_env_key else "none"),
        "monthly_budget_usd": round(budget, 2),
        "model_fast": model_fast,
        "model_pro": model_pro,
        "available_models": AVAILABLE_MODELS,
        "usage": usage,
        "remaining_usd": round(max(0.0, budget - usage["spent_usd"]), 4),
        "status": store.get_value(db, _STATUS_KEY) or {},
        "paused_until": paused_until(db),
    }


def save_ai_config(
    db: Session,
    *,
    api_key: str | None = None,
    clear_api_key: bool = False,
    monthly_budget_usd: float | None = None,
    model_fast: str | None = None,
    model_pro: str | None = None,
) -> dict[str, Any]:
    if clear_api_key:
        store.delete_value(db, _SECRET_KEY)
        store.delete_value(db, _STATUS_KEY)
    elif api_key is not None and api_key.strip():
        store.set_secret(db, _SECRET_KEY, {"api_key": api_key.strip()})
        store.delete_value(db, _STATUS_KEY)  # a new key starts with a clean slate

    cfg = dict(store.get_value(db, _CONFIG_KEY) or {})
    if monthly_budget_usd is not None:
        cfg["monthly_budget_usd"] = max(0.5, min(100.0, float(monthly_budget_usd)))
    if model_fast:
        cfg["model_fast"] = model_fast.strip()
    if model_pro:
        cfg["model_pro"] = model_pro.strip()
    store.set_value(db, _CONFIG_KEY, cfg)
    return get_ai_config(db)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = MODEL_PRICING_USD_PER_M.get(model, (1.50, 7.50))
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000.0


def monthly_usage(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    row = db.execute(
        select(
            func.count(AIUsageLog.id),
            func.coalesce(func.sum(AIUsageLog.input_tokens), 0),
            func.coalesce(func.sum(AIUsageLog.output_tokens), 0),
            func.coalesce(func.sum(AIUsageLog.estimated_cost_usd), 0.0),
        ).where(AIUsageLog.created_at >= month_start)
    ).one()
    return {
        "month": month_start.strftime("%Y-%m"),
        "calls": int(row[0] or 0),
        "input_tokens": int(row[1] or 0),
        "output_tokens": int(row[2] or 0),
        "spent_usd": round(float(row[3] or 0.0), 4),
    }


_ENDPOINTS = {
    "studio_v1beta": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    "studio_v1": "https://generativelanguage.googleapis.com/v1/models/{model}:generateContent",
    "vertex": "https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent",
}
# The endpoint that last answered for a key, so later calls go straight there.
_working_endpoint: dict[str, str] = {}
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_WAITS_S = (10.0, 30.0)  # two retries when the model is overloaded or slow
TIMEOUT_S = 150.0  # gemini-4 models think before answering; a minute is normal under load


def paused_until(db: Session) -> str | None:
    """When Google's quota for the key is used up: the UTC time it resets, else None."""
    until = (store.get_value(db, _STATUS_KEY) or {}).get("paused_until")
    return until if until and until > utcnow().isoformat() + "Z" else None


def _endpoint_order(api_key: str) -> list[str]:
    """Google AI Studio first for every key (Vertex Express keys work there too); Vertex last,
    for keys that only that endpoint accepts. The key goes in a header, never in the URL."""
    order = ["studio_v1beta", "studio_v1", "vertex"]
    known = _working_endpoint.get(api_key[-12:])
    if known in order:
        order.remove(known)
        order.insert(0, known)
    return order


def _extract_json_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        reason = (payload.get("promptFeedback") or {}).get("blockReason")
        raise GeminiError(f"Gemini returned no answer{f' ({reason})' if reason else ''}")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(str(p.get("text") or "") for p in parts if not p.get("thought")).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text:
        finish = candidates[0].get("finishReason")
        raise GeminiError(f"Gemini returned an empty answer ({finish or 'no reason given'})")
    return text


def _parse_lenient(text: str) -> Any:
    """json.loads, forgiving the slips models make: text around the object, trailing commas."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        fixed = re.sub(r",\s*([}\]])", r"\1", text[start : end + 1])
        return json.loads(fixed)


def _short(exc_or_text: Any) -> str:
    text = str(exc_or_text)
    try:
        err = json.loads(text[text.index("{") :]).get("error") or {}
        if err.get("message"):
            return f"{err.get('code', '')} {err['message']}".strip()[:240]
    except (ValueError, AttributeError):
        pass
    return text[:240]


def _post(
    api_key: str, model: str, body: dict[str, Any], *, timeout_s: float, retries: int | None = None
) -> dict[str, Any]:
    """One request with endpoint discovery and retries; touches no database."""
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    last: str = "Gemini request failed"
    with httpx.Client(timeout=httpx.Timeout(timeout_s, connect=15.0)) as client:
        waits = RETRY_WAITS_S if retries is None else RETRY_WAITS_S[:retries]
        for attempt in range(len(waits) + 1):
            retry = False
            for name in _endpoint_order(api_key):
                url = _ENDPOINTS[name].format(model=model)
                try:
                    resp = client.post(url, json=body, headers=headers)
                except httpx.TimeoutException:
                    last, retry = f"Gemini did not answer within {timeout_s:.0f} s", True
                    break  # the endpoint is right, the model is slow: retry later, don't hop
                except httpx.HTTPError as exc:
                    last = f"Network error calling Gemini: {type(exc).__name__}"
                    continue
                if resp.status_code in (401, 403, 404):
                    if not retry:  # keep the overload message; it is the one that matters
                        last = f"HTTP {resp.status_code}: {_short(resp.text)}"
                    continue  # this endpoint does not take this key or model; try the next
                if resp.status_code == 429 and (pause := _quota_pause(resp)) is not None:
                    until = (utcnow() + timedelta(seconds=pause[1])).isoformat() + "Z"
                    raise QuotaPausedError(f"Google quota used up: {pause[0]}", until)
                if resp.status_code in RETRY_STATUS:
                    # overloaded: the other endpoint is sometimes served by other capacity
                    last, retry = f"HTTP {resp.status_code}: {_short(resp.text)}", True
                    continue
                if resp.status_code >= 400:
                    raise GeminiError(f"HTTP {resp.status_code}: {_short(resp.text)}")
                _working_endpoint[api_key[-12:]] = name
                return resp.json()
            if not retry or attempt == len(waits):
                break
            logger.info("Gemini busy (%s); retrying in %.0f s", last, waits[attempt])
            time.sleep(waits[attempt])
    raise GeminiError(last)


def _record_status(
    db: Session,
    *,
    ok: bool,
    feature: str,
    model: str,
    latency_s: float,
    error: str = "",
    paused_until: str | None = None,
) -> None:
    status = dict(store.get_value(db, _STATUS_KEY) or {})
    now = utcnow().isoformat() + "Z"
    status.update({"last_at": now, "last_feature": feature, "last_model": model, "last_ok": ok})
    status.pop("paused_until", None)
    if paused_until:
        status["paused_until"] = paused_until
    if ok:
        status.update({"last_ok_at": now, "last_latency_s": round(latency_s, 1)})
    else:
        status.update({"last_error": error[:300], "last_error_at": now})
    store.set_value(db, _STATUS_KEY, status)


def generate_json(
    *,
    feature: str,
    system_prompt: str,
    user_payload: dict[str, Any],
    tier: str = "fast",
    temperature: float = 0.25,
    max_output_tokens: int = 4096,
    timeout_s: float = TIMEOUT_S,
    retries: int | None = None,
    retry_invalid: bool = True,
) -> tuple[dict[str, Any], str]:
    """Ask Gemini for a JSON object, within the monthly budget, and log the spend.

    Opens its own short database sessions and holds none while waiting for Gemini, so a slow model
    never blocks the rest of the app. Call it from background work, not from a request handler.
    Returns `(parsed_json, model_used)`.
    """
    from routepass.db import session_scope

    with session_scope() as db:
        api_key = get_api_key(db)
        if not api_key:
            raise GeminiNotConfiguredError("Gemini API key is not configured")
        cfg = get_ai_config(db)
    paused = (cfg.get("status") or {}).get("paused_until")
    if paused and paused > utcnow().isoformat() + "Z":
        raise QuotaPausedError(
            f"Google quota used up; the AI coach resumes at {paused[:16].replace('T', ' ')} UTC", paused
        )
    if cfg["usage"]["spent_usd"] >= cfg["monthly_budget_usd"]:
        raise BudgetExceededError(
            f"Monthly Gemini budget reached (${cfg['usage']['spent_usd']:.2f} of ${cfg['monthly_budget_usd']:.2f})"
        )

    model = cfg["model_pro"] if tier == "pro" else cfg["model_fast"]
    gen_cfg: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens,
        "responseMimeType": "application/json",
    }
    if model.startswith("gemini-4-"):
        gen_cfg["thinkingConfig"] = {"thinkingLevel": "high" if tier == "pro" else "low"}
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": json.dumps(user_payload, separators=(",", ":"), default=str)}],
            }
        ],
        "generationConfig": gen_cfg,
    }

    started = time.monotonic()
    try:
        data = _post(api_key, model, body, timeout_s=timeout_s, retries=retries)
    except GeminiError as exc:
        with session_scope() as db:
            _record_status(
                db,
                ok=False,
                feature=feature,
                model=model,
                latency_s=0,
                error=str(exc),
                paused_until=getattr(exc, "until", None),
            )
        raise

    meta = data.get("usageMetadata") or {}
    in_tok = int(meta.get("promptTokenCount") or 0)
    # thinking is billed as output
    out_tok = int(meta.get("candidatesTokenCount") or 0) + int(meta.get("thoughtsTokenCount") or 0)
    error = ""
    parsed: Any = None
    try:
        parsed = _parse_lenient(_extract_json_text(data))
        if not isinstance(parsed, dict):
            error = "Gemini's answer was not a JSON object"
    except json.JSONDecodeError as exc:
        error = f"Gemini returned invalid JSON: {exc}"
    except GeminiError as exc:
        error = str(exc)
    with session_scope() as db:
        db.add(
            AIUsageLog(
                feature=feature,
                model=model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                estimated_cost_usd=estimate_cost_usd(model, in_tok, out_tok),
            )
        )
        _record_status(
            db, ok=not error, feature=feature, model=model, latency_s=time.monotonic() - started, error=error
        )
    if error:
        logger.warning("Gemini %s: %s", feature, error)
        if error.startswith("Gemini returned invalid JSON") and retry_invalid:
            # a malformed answer is rare and random: ask once more
            return generate_json(
                feature=feature,
                system_prompt=system_prompt,
                user_payload=user_payload,
                tier=tier,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                timeout_s=timeout_s,
                retries=0,
                retry_invalid=False,
            )
        raise GeminiError(error)
    return parsed, model


def check_connection() -> dict[str, Any]:
    """A tiny request that proves key, endpoint and model work. Costs a fraction of a cent."""
    started = time.monotonic()
    try:
        res, model = generate_json(
            feature="test",
            system_prompt="You check that an API connection works.",
            user_payload={"task": 'Reply with exactly {"ok": true}'},
            max_output_tokens=256,
        )
    except GeminiError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": bool(res.get("ok")), "model": model, "latency_s": round(time.monotonic() - started, 1)}
