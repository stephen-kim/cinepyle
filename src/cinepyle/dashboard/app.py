"""FastAPI web dashboard for cinepyle settings management.

Serves an HTMX + Tailwind CSS settings page. Each section POSTs
to its own endpoint and receives a partial HTML fragment for
in-place updates without full page reloads.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time as _time
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="cinePyle Dashboard")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Provider display names
_PROVIDER_NAMES = {
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI (GPT)",
    "gemini": "Google (Gemini)",
}


def _get_mgr():
    from cinepyle.dashboard.settings_manager import SettingsManager
    return SettingsManager.get_instance()


def _get_imax_theaters() -> list[dict]:
    """Load CGV IMAX theaters sorted by name."""
    from cinepyle.theaters.data_cgv import get_imax_theaters
    return sorted(get_imax_theaters(), key=lambda t: t["TheaterName"])


# ------------------------------------------------------------------
# All-chain theater cache (for preferred theater search)
# ------------------------------------------------------------------

_theater_cache: list[dict] = []
_theater_cache_ts: float = 0.0
_THEATER_CACHE_TTL = 3600  # 1 hour

_CHAIN_DISPLAY = {
    "cgv": "CGV",
    "lotte": "롯데시네마",
    "megabox": "메가박스",
    "cineq": "씨네Q",
}


def _build_theater_cache() -> list[dict]:
    """Build merged theater list across all chains (blocking I/O for Lotte/Megabox)."""
    global _theater_cache, _theater_cache_ts

    now = _time.time()
    if _theater_cache and (now - _theater_cache_ts) < _THEATER_CACHE_TTL:
        return _theater_cache

    all_theaters: list[dict] = []

    # CGV (static)
    from cinepyle.theaters.data_cgv import data as cgv_data
    for t in cgv_data:
        all_theaters.append({
            "chain_key": "cgv",
            "theater_code": t["TheaterCode"],
            "region_code": t.get("RegionCode", ""),
            "name": t["TheaterName"],
        })

    # CineQ (static)
    try:
        from cinepyle.theaters.data_cineq import data as cineq_data
        for t in cineq_data:
            all_theaters.append({
                "chain_key": "cineq",
                "theater_code": t["TheaterCode"],
                "region_code": "",
                "name": t["TheaterName"],
            })
    except Exception:
        logger.exception("Failed to load CineQ theaters")

    # Lotte (API)
    try:
        from cinepyle.theaters import lotte
        for t in lotte.get_theater_list():
            all_theaters.append({
                "chain_key": "lotte",
                "theater_code": str(t.get("TheaterID", "")),
                "region_code": "",
                "name": t["TheaterName"],
            })
    except Exception:
        logger.exception("Failed to fetch Lotte theaters")

    # Megabox (API)
    try:
        from cinepyle.theaters import megabox
        for t in megabox.get_theater_list():
            all_theaters.append({
                "chain_key": "megabox",
                "theater_code": str(t.get("TheaterID", t.get("brchNo", ""))),
                "region_code": "",
                "name": t["TheaterName"],
            })
    except Exception:
        logger.exception("Failed to fetch Megabox theaters")

    _theater_cache = all_theaters
    _theater_cache_ts = now
    return all_theaters


def _cred_exists(mgr, key: str) -> bool:
    """Check if a credential has a value (from dashboard or .env)."""
    return bool(mgr.get(key, ""))


# Mapping: credential form key → .env config attribute name
_CRED_ENV_MAP: dict[str, str] = {
    "credential:cgv_id": "CGV_ID",
    "credential:cgv_password": "CGV_PASSWORD",
    "credential:lottecinema_id": "LOTTECINEMA_ID",
    "credential:lottecinema_password": "LOTTECINEMA_PASSWORD",
    "credential:megabox_id": "MEGABOX_ID",
    "credential:megabox_password": "MEGABOX_PASSWORD",
    "credential:cineq_id": "CINEQ_ID",
    "credential:cineq_password": "CINEQ_PASSWORD",
    "credential:anthropic_api_key": "ANTHROPIC_API_KEY",
    "credential:openai_api_key": "OPENAI_API_KEY",
    "credential:gemini_api_key": "GEMINI_API_KEY",
    "credential:kofic_api_key": "KOBIS_API_KEY",
    "credential:watcha_email": "WATCHA_EMAIL",
    "credential:watcha_password": "WATCHA_PASSWORD",
    "credential:naver_maps_client_id": "NAVER_MAPS_CLIENT_ID",
    "credential:naver_maps_client_secret": "NAVER_MAPS_CLIENT_SECRET",
    "credential:telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "credential:telegram_chat_id": "TELEGRAM_CHAT_ID",
}


def _env_cred_set(key: str) -> bool:
    """Check if a credential is set via .env (environment variable)."""
    import cinepyle.config as cfg
    attr = _CRED_ENV_MAP.get(key, "")
    if not attr:
        return False
    return bool(getattr(cfg, attr, ""))


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index():
    return RedirectResponse(url="/settings", status_code=302)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    mgr = _get_mgr()

    # Intervals
    imax_interval = mgr.get("imax_check_interval", "600")
    new_movie_interval = mgr.get("new_movie_check_interval", "3600")

    # IMAX theaters (checkbox list)
    imax_theaters = _get_imax_theaters()
    imax_selected_codes = {t["code"] for t in mgr.get_imax_monitor_theaters()}

    # Migration: old single theater → new lists (one-time)
    if not mgr.get("imax_monitor_theaters") and mgr.get("preferred_theater_code"):
        from cinepyle.theaters.data_cgv import IMAX_THEATER_CODES
        old_code = mgr.get("preferred_theater_code")
        old_region = mgr.get("preferred_theater_region", "")
        old_name = mgr.get("preferred_theater_name", "")
        if old_code and old_code in IMAX_THEATER_CODES:
            await mgr.set("imax_monitor_theaters", json.dumps(
                [{"code": old_code, "region": old_region, "name": old_name}],
                ensure_ascii=False,
            ))
            imax_selected_codes = {old_code}

    # Preferred theaters
    preferred_theaters = mgr.get_preferred_theaters()

    # LLM priority
    llm_priority = mgr.get_llm_priority()

    # Credentials — check which ones are set (dashboard DB or .env)
    creds: dict[str, bool] = {}
    env_creds: dict[str, bool] = {}
    for key_prefix in _CRED_ENV_MAP:
        creds[key_prefix] = _cred_exists(mgr, key_prefix)
        env_creds[key_prefix] = _env_cred_set(key_prefix)

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "imax_interval": imax_interval,
            "new_movie_interval": new_movie_interval,
            "imax_theaters": imax_theaters,
            "imax_selected_codes": imax_selected_codes,
            "preferred_theaters": preferred_theaters,
            "llm_priority": llm_priority,
            "creds": creds,
            "env_creds": env_creds,
        },
    )


@app.post("/settings/intervals", response_class=HTMLResponse)
async def update_intervals(
    request: Request,
    imax_interval: int = Form(...),
    new_movie_interval: int = Form(...),
):
    mgr = _get_mgr()

    # Validate
    imax_interval = max(60, min(86400, imax_interval))
    new_movie_interval = max(60, min(86400, new_movie_interval))

    await mgr.set("imax_check_interval", str(imax_interval))
    await mgr.set("new_movie_check_interval", str(new_movie_interval))

    # Reschedule running jobs
    try:
        from cinepyle.notifications.imax import check_imax_job
        from cinepyle.notifications.new_movie import check_new_movies_job

        await mgr.reschedule_job("imax_check", check_imax_job, imax_interval)
        await mgr.reschedule_job(
            "new_movie_check", check_new_movies_job, new_movie_interval
        )
    except Exception:
        logger.exception("Failed to reschedule jobs")

    return templates.TemplateResponse(
        request=request,
        name="partials/intervals_status.html",
        context={
            "imax_interval": imax_interval,
            "new_movie_interval": new_movie_interval,
        },
    )


@app.post("/settings/imax-theaters", response_class=HTMLResponse)
async def update_imax_theaters(request: Request):
    """Save selected IMAX monitor theaters (checkbox form)."""
    mgr = _get_mgr()
    form = await request.form()

    # Checkboxes: multiple values with name "imax_theater"
    # Each value is "code:region:name"
    selected = form.getlist("imax_theater")

    theaters: list[dict] = []
    for val in selected:
        parts = val.split(":", 2)
        if len(parts) == 3:
            theaters.append({"code": parts[0], "region": parts[1], "name": parts[2]})

    await mgr.set(
        "imax_monitor_theaters", json.dumps(theaters, ensure_ascii=False)
    )

    names = [t["name"] for t in theaters]
    return templates.TemplateResponse(
        request=request,
        name="partials/imax_theaters_status.html",
        context={"theater_names": names, "count": len(theaters)},
    )


@app.post("/settings/preferred-theaters", response_class=HTMLResponse)
async def update_preferred_theaters(request: Request):
    """Save preferred theaters list (JSON from hidden input)."""
    mgr = _get_mgr()
    form = await request.form()

    raw = form.get("preferred_theaters_json", "[]")
    try:
        theaters = json.loads(raw)
    except json.JSONDecodeError:
        return templates.TemplateResponse(
            request=request,
            name="partials/error.html",
            context={"message": "잘못된 데이터입니다."},
        )

    await mgr.set(
        "preferred_theaters", json.dumps(theaters, ensure_ascii=False)
    )

    return templates.TemplateResponse(
        request=request,
        name="partials/preferred_theaters_status.html",
        context={"count": len(theaters)},
    )


@app.get("/api/theaters/search", response_class=HTMLResponse)
async def search_theaters(request: Request, q: str = Query("")):
    """HTMX endpoint: search theaters across all chains."""
    if len(q.strip()) < 1:
        return HTMLResponse("")

    query = q.strip().lower()
    all_theaters = await asyncio.to_thread(_build_theater_cache)

    matches = [t for t in all_theaters if query in t["name"].lower()][:20]

    return templates.TemplateResponse(
        request=request,
        name="partials/theater_search_results.html",
        context={"results": matches, "chain_display": _CHAIN_DISPLAY},
    )


@app.post("/settings/llm-priority", response_class=HTMLResponse)
async def update_llm_priority(request: Request):
    mgr = _get_mgr()
    form = await request.form()

    # Multiple values with the same name "priority"
    priority = form.getlist("priority")
    valid_providers = {"anthropic", "openai", "gemini"}
    priority = [p for p in priority if p in valid_providers]

    if not priority:
        priority = ["anthropic", "openai", "gemini"]

    await mgr.set("llm_priority", json.dumps(priority))
    mgr.reset_engines()

    display = " > ".join(_PROVIDER_NAMES.get(p, p) for p in priority)
    return templates.TemplateResponse(
        request=request,
        name="partials/llm_status.html",
        context={"priority_display": display},
    )


@app.post("/settings/credentials", response_class=HTMLResponse)
async def update_credentials(request: Request):
    mgr = _get_mgr()
    form = await request.form()

    count = 0
    for key, value in form.items():
        if key.startswith("credential:") and value.strip():
            await mgr.set(key, value.strip(), encrypted=True)
            count += 1

    if count > 0:
        mgr.reset_engines()

    return templates.TemplateResponse(
        request=request,
        name="partials/credentials_status.html",
        context={"count": count},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
