"""Cost-aware Gemini client for RoutePass adaptive training plans.

Supports both:
- Google Cloud Vertex AI Express / API keys (`AQ....`) via aiplatform.googleapis.com
- Google AI Studio API keys (`AIza...`) via generativelanguage.googleapis.com

Enforces a hard monthly USD budget cap tracked in `ai_usage_log` so your $10/mo
Google Cloud credits are used efficiently and never unexpectedly exceeded.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
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
    "gemini-2.5-flash-lite": (0.075, 0.30),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.0-flash": (0.10, 0.40),
}

_SECRET_KEY = "gemini.credentials"
_CONFIG_KEY = "gemini.config"


class GeminiError(RuntimeError):
    """Base error for Gemini calls."""


class GeminiNotConfiguredError(GeminiError):
    """Raised when no Gemini API key is configured."""


class BudgetExceededError(GeminiError):
    """Raised when the monthly Gemini USD budget cap has been reached."""


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
        "usage": usage,
        "remaining_usd": round(max(0.0, budget - usage["spent_usd"]), 4),
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
    elif api_key is not None and api_key.strip():
        store.set_secret(db, _SECRET_KEY, {"api_key": api_key.strip()})

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
    in_rate, out_rate = MODEL_PRICING_USD_PER_M.get(model, (0.30, 1.20))
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


def _endpoints_for_key(api_key: str, model: str) -> list[str]:
    """Return ordered candidate REST endpoints for a given API key format."""
    vertex_url = (
        f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent"
        f"?key={api_key}"
    )
    aistudio_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )
    # Vertex AI Express keys start with "AQ."; AI Studio keys start with "AIza"
    if api_key.startswith("AQ."):
        return [vertex_url, aistudio_url]
    return [aistudio_url, vertex_url]


def _extract_json_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise GeminiError("Gemini returned no candidates")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(str(p.get("text") or "") for p in parts).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def generate_json(
    db: Session,
    *,
    feature: str,
    system_prompt: str,
    user_payload: dict[str, Any],
    tier: str = "fast",
    temperature: float = 0.25,
    max_output_tokens: int = 4096,
    timeout_s: float = 45.0,
) -> tuple[dict[str, Any], str]:
    """Call Gemini with JSON output mode, enforcing monthly budget & logging token spend.

    Returns `(parsed_json, model_used)`.
    """
    api_key = get_api_key(db)
    if not api_key:
        raise GeminiNotConfiguredError("Gemini API key is not configured")

    cfg = get_ai_config(db)
    if cfg["usage"]["spent_usd"] >= cfg["monthly_budget_usd"]:
        raise BudgetExceededError(
            f"Monthly Gemini budget reached (${cfg['usage']['spent_usd']:.2f} / ${cfg['monthly_budget_usd']:.2f})"
        )

    model = cfg["model_pro"] if tier == "pro" else cfg["model_fast"]
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": json.dumps(user_payload, separators=(",", ":"), default=str)}],
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
            "responseMimeType": "application/json",
        },
    }

    last_err: Exception | None = None
    data: dict[str, Any] | None = None
    with httpx.Client(timeout=timeout_s) as client:
        for url in _endpoints_for_key(api_key, model):
            try:
                resp = client.post(url, json=body)
                if resp.status_code in (401, 403, 404):
                    last_err = GeminiError(f"HTTP {resp.status_code}: {resp.text[:240]}")
                    continue
                if resp.status_code >= 400:
                    raise GeminiError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                break
            except httpx.HTTPError as exc:
                last_err = GeminiError(f"Network error calling Gemini: {exc}")
                continue

    if data is None:
        raise last_err or GeminiError("Gemini request failed")

    meta = data.get("usageMetadata") or {}
    in_tok = int(meta.get("promptTokenCount") or 0)
    out_tok = int(meta.get("candidatesTokenCount") or 0)
    cost = estimate_cost_usd(model, in_tok, out_tok)
    db.add(
        AIUsageLog(
            feature=feature,
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            estimated_cost_usd=cost,
        )
    )
    db.flush()

    raw_text = _extract_json_text(data)
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.warning("Gemini returned invalid JSON for %s: %s", feature, raw_text[:200])
        raise GeminiError(f"Gemini returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise GeminiError("Gemini JSON response was not an object")
    return parsed, model
