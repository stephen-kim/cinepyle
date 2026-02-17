"""FastAPI web dashboard for cinepyle settings management.

Serves an HTMX + Tailwind CSS settings page. Each section POSTs
to its own endpoint and receives a partial HTML fragment for
in-place updates without full page reloads.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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

# Mapping: provider name → credential key for API key
_PROVIDER_API_KEY_MAP = {
    "anthropic": "credential:anthropic_api_key",
    "openai": "credential:openai_api_key",
    "gemini": "credential:gemini_api_key",
}


def _provider_has_key(mgr, provider: str) -> bool:
    """Check if a provider has an API key set (via dashboard or .env)."""
    cred_key = _PROVIDER_API_KEY_MAP.get(provider, "")
    if not cred_key:
        return False
    # Check dashboard DB
    if mgr.get(cred_key, ""):
        return True
    # Check .env
    return _env_cred_set(cred_key)


def _get_mgr():
    from cinepyle.dashboard.settings_manager import SettingsManager
    return SettingsManager.get_instance()


# Chain display names (for search results)
_CHAIN_DISPLAY = {
    "cgv": "CGV",
    "lotte": "롯데시네마",
    "megabox": "메가박스",
    "cineq": "씨네Q",
    "indie": "독립영화관",
}


def _get_static_theaters() -> list[dict]:
    """Fallback: return static theater data (CGV + CineQ + indie) when DB cache is empty."""
    theaters: list[dict] = []
    try:
        from cinepyle.theaters.data_cgv import data as cgv_data
        for t in cgv_data:
            theaters.append({
                "chain_key": "cgv",
                "theater_code": t["TheaterCode"],
                "region_code": t.get("RegionCode", ""),
                "name": t["TheaterName"],
            })
    except Exception:
        pass
    try:
        from cinepyle.theaters.data_cineq import data as cineq_data
        for t in cineq_data:
            theaters.append({
                "chain_key": "cineq",
                "theater_code": t["TheaterCode"],
                "region_code": "",
                "name": t["TheaterName"],
            })
    except Exception:
        pass
    try:
        from cinepyle.theaters.data_indie import data as indie_data
        for t in indie_data:
            theaters.append({
                "chain_key": "indie",
                "theater_code": "",
                "region_code": "",
                "name": t["TheaterName"],
            })
    except Exception:
        pass
    return theaters


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
    screen_check_interval = mgr.get("screen_check_interval", "600")
    new_movie_interval = mgr.get("new_movie_check_interval", "3600")

    # Screen monitors
    screen_monitors = mgr.get_screen_monitors()

    # Migration: old IMAX monitors → new screen monitors (one-time)
    if not mgr.get("screen_monitors") and mgr.get("imax_monitor_theaters"):
        old_imax = mgr.get_imax_monitor_theaters()
        if old_imax:
            migrated: list[dict] = []
            for t in old_imax:
                migrated.append({
                    "chain_key": "cgv",
                    "theater_code": t.get("code", ""),
                    "theater_name": t.get("name", ""),
                    "screen_filter": "IMAX",
                })
            await mgr.set(
                "screen_monitors",
                json.dumps(migrated, ensure_ascii=False),
            )
            screen_monitors = migrated

    # Preferred theaters
    preferred_theaters = mgr.get_preferred_theaters()

    # LLM priority — only show providers that have an API key configured
    all_llm_priority = mgr.get_llm_priority()
    llm_priority = [p for p in all_llm_priority if _provider_has_key(mgr, p)]

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
            "screen_check_interval": screen_check_interval,
            "new_movie_interval": new_movie_interval,
            "screen_monitors": screen_monitors,
            "preferred_theaters": preferred_theaters,
            "llm_priority": llm_priority,
            "creds": creds,
            "env_creds": env_creds,
            "chain_display": _CHAIN_DISPLAY,
        },
    )


@app.post("/settings/intervals", response_class=HTMLResponse)
async def update_intervals(
    request: Request,
    screen_check_interval: int = Form(...),
    new_movie_interval: int = Form(...),
):
    mgr = _get_mgr()

    # Validate
    screen_check_interval = max(60, min(86400, screen_check_interval))
    new_movie_interval = max(60, min(86400, new_movie_interval))

    await mgr.set("screen_check_interval", str(screen_check_interval))
    await mgr.set("new_movie_check_interval", str(new_movie_interval))

    # Reschedule running jobs
    try:
        from cinepyle.notifications.screen_monitor import check_screens_job
        from cinepyle.notifications.new_movie import check_new_movies_job

        await mgr.reschedule_job(
            "screen_monitor", check_screens_job, screen_check_interval
        )
        await mgr.reschedule_job(
            "new_movie_check", check_new_movies_job, new_movie_interval
        )
    except Exception:
        logger.exception("Failed to reschedule jobs")

    return templates.TemplateResponse(
        request=request,
        name="partials/intervals_status.html",
        context={
            "screen_check_interval": screen_check_interval,
            "new_movie_interval": new_movie_interval,
        },
    )


@app.post("/settings/screen-monitors", response_class=HTMLResponse)
async def update_screen_monitors(request: Request):
    """Save screen monitor list (JSON from hidden input)."""
    mgr = _get_mgr()
    form = await request.form()

    raw = form.get("screen_monitors_json", "[]")
    try:
        monitors = json.loads(raw)
    except json.JSONDecodeError:
        return templates.TemplateResponse(
            request=request,
            name="partials/error.html",
            context={"message": "잘못된 데이터입니다."},
        )

    await mgr.set(
        "screen_monitors", json.dumps(monitors, ensure_ascii=False)
    )

    return templates.TemplateResponse(
        request=request,
        name="partials/monitor_status.html",
        context={"count": len(monitors)},
    )


@app.get("/api/theaters/{chain_key}/{theater_code}/screens")
async def get_theater_screens(chain_key: str, theater_code: str):
    """Return screen/hall names for a theater (JSON API for UI)."""
    from cinepyle.scrapers.screens import fetch_screen_names

    try:
        names = await asyncio.to_thread(fetch_screen_names, chain_key, theater_code)
    except Exception:
        logger.exception("Screen names fetch failed for %s/%s", chain_key, theater_code)
        names = []

    return JSONResponse(content={"screens": names})


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
async def search_theaters(
    request: Request,
    q: str = Query(""),
    context: str = Query("preferred"),
):
    """HTMX endpoint: search theaters across all chains (from DB cache).

    context="preferred" → for preferred theaters card (add directly)
    context="monitor"   → for screen monitor card (choose whole or per-screen)
    """
    if len(q.strip()) < 1:
        return HTMLResponse("")

    query = q.strip().lower()
    mgr = _get_mgr()
    all_theaters = mgr.get_cached_theater_list()

    # Fallback to static data if DB cache is empty (first run before sync)
    if not all_theaters:
        all_theaters = _get_static_theaters()

    matches = [t for t in all_theaters if query in t["name"].lower()][:20]

    template_name = (
        "partials/monitor_search_results.html"
        if context == "monitor"
        else "partials/theater_search_results.html"
    )

    return templates.TemplateResponse(
        request=request,
        name=template_name,
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

    # Build updated LLM priority list (only providers with keys)
    all_llm_priority = mgr.get_llm_priority()
    available_providers = [p for p in all_llm_priority if _provider_has_key(mgr, p)]

    return templates.TemplateResponse(
        request=request,
        name="partials/credentials_status.html",
        context={
            "count": count,
            "llm_priority": available_providers,
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
