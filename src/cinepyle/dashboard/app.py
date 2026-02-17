"""FastAPI web dashboard for cinepyle settings management.

Serves an HTMX + Tailwind CSS settings page. Each section POSTs
to its own endpoint and receives a partial HTML fragment for
in-place updates without full page reloads.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, Form, Request
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


def _get_theaters() -> list[dict]:
    """Load CGV theater data sorted by name."""
    from cinepyle.theaters.data_cgv import data
    return sorted(data, key=lambda t: t["TheaterName"])


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

    # Theater
    current_theater_code = mgr.get("preferred_theater_code", "0013")
    theaters = _get_theaters()

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
            "theaters": theaters,
            "current_theater_code": current_theater_code,
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


@app.post("/settings/theater", response_class=HTMLResponse)
async def update_theater(request: Request, theater: str = Form(...)):
    mgr = _get_mgr()

    # theater value format: "code:region:name"
    parts = theater.split(":", 2)
    if len(parts) != 3:
        return templates.TemplateResponse(
            request=request,
            name="partials/error.html",
            context={"message": "잘못된 영화관 데이터입니다."},
        )

    code, region, name = parts
    await mgr.set("preferred_theater_code", code)
    await mgr.set("preferred_theater_region", region)
    await mgr.set("preferred_theater_name", name)

    return templates.TemplateResponse(
        request=request,
        name="partials/theater_status.html",
        context={"theater_name": name},
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
