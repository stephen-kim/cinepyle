"""FastAPI dashboard for digest, screen alert, and sync settings."""

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cinepyle.digest.settings import DigestSettings
from cinepyle.notifications.screen_settings import ScreenAlertSettings
from cinepyle.theaters.models import TheaterDatabase
from cinepyle.theaters.sync_settings import SyncSettings

logger = logging.getLogger(__name__)

app = FastAPI(title="Cinepyle Dashboard")

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

# Reference to the bot's job_queue, set by main.py at startup
_job_queue = None
_chat_id: str = ""


def set_bot_context(job_queue, chat_id: str) -> None:
    """Store references so the dashboard can trigger jobs."""
    global _job_queue, _chat_id
    _job_queue = job_queue
    _chat_id = chat_id


_REGION_ORDER = ["서울", "경기", "인천", "강원", "충청", "전라", "경상", "제주"]


def _base_context(request: Request, active_tab: str = "digest", **extra):
    """Build the common template context."""
    db = TheaterDatabase.load()
    chains = {
        "cgv": db.get_by_chain("cgv"),
        "lotte": db.get_by_chain("lotte"),
        "megabox": db.get_by_chain("megabox"),
        "cineq": db.get_by_chain("cineq"),
        "indie": db.get_by_chain("indie"),
    }

    # Build region → theaters mapping (all chains merged, sorted)
    regions: dict[str, list] = {}
    for region_name in _REGION_ORDER:
        theaters_in_region = db.get_by_region(region_name)
        if theaters_in_region:
            regions[region_name] = theaters_in_region

    last_sync_at = db.last_sync_at
    db.close()

    # Detect which env vars are set (for showing "env로 할당됨" in UI)
    env_vars = {
        "LLM_PROVIDER": bool(os.environ.get("LLM_PROVIDER")),
        "LLM_MODEL": bool(os.environ.get("LLM_MODEL")),
        "LLM_API_KEY": bool(os.environ.get("LLM_API_KEY")),
        "TELEGRAM_BOT_TOKEN": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
        "TELEGRAM_CHAT_ID": bool(os.environ.get("TELEGRAM_CHAT_ID")),
        "KOFIC_API_KEY": bool(os.environ.get("KOFIC_API_KEY")),
        "NAVER_MAP_CLIENT_ID": bool(os.environ.get("NAVER_MAP_CLIENT_ID")),
        "NAVER_MAP_CLIENT_SECRET": bool(os.environ.get("NAVER_MAP_CLIENT_SECRET")),
        "WATCHA_EMAIL": bool(os.environ.get("WATCHA_EMAIL")),
        "WATCHA_PASSWORD": bool(os.environ.get("WATCHA_PASSWORD")),
        "CGV_ID": bool(os.environ.get("CGV_ID")),
        "CGV_PASSWORD": bool(os.environ.get("CGV_PASSWORD")),
        "LOTTE_ID": bool(os.environ.get("LOTTE_ID")),
        "LOTTE_PASSWORD": bool(os.environ.get("LOTTE_PASSWORD")),
        "MEGABOX_ID": bool(os.environ.get("MEGABOX_ID")),
        "MEGABOX_PASSWORD": bool(os.environ.get("MEGABOX_PASSWORD")),
    }

    return {
        "request": request,
        "settings": DigestSettings.load(),
        "screen_settings": ScreenAlertSettings.load(),
        "sync_settings": SyncSettings.load(),
        "chains": chains,
        "regions": regions,
        "last_sync_at": last_sync_at,
        "active_tab": active_tab,
        "env_vars": env_vars,
        "saved": False,
        "test_sent": False,
        "screen_saved": False,
        "sync_saved": False,
        "sync_triggered": False,
        **extra,
    }


# -----------------------------------------------------------------------
# Digest settings
# -----------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    ctx = _base_context(request, active_tab="digest")
    return templates.TemplateResponse("index.html", ctx)


@app.post("/settings", response_class=HTMLResponse)
async def save_settings(
    request: Request,
    google_enabled: bool = Form(False),
    cine21_enabled: bool = Form(False),
    watcha_enabled: bool = Form(False),
    schedule_enabled: bool = Form(False),
    schedule_hour: int = Form(9),
    schedule_minute: int = Form(0),
    llm_provider: str = Form("openai"),
    llm_api_key: str = Form(""),
    preferences: str = Form(""),
):
    current = DigestSettings.load()
    if not llm_api_key and current.llm_api_key:
        llm_api_key = current.llm_api_key

    settings = DigestSettings(
        sources_enabled={
            "google": google_enabled,
            "cine21": cine21_enabled,
            "watcha": watcha_enabled,
        },
        schedule_enabled=schedule_enabled,
        schedule_hour=schedule_hour,
        schedule_minute=schedule_minute,
        llm_provider=llm_provider,
        llm_model=current.llm_model,
        llm_api_key=llm_api_key,
        preferences=preferences,
    )
    settings.save()
    logger.info("Digest settings saved")

    ctx = _base_context(request, active_tab="digest", saved=True)
    ctx["settings"] = settings
    return templates.TemplateResponse("index.html", ctx)


@app.post("/test-digest", response_class=HTMLResponse)
async def test_digest(request: Request):
    if _job_queue is not None:
        from cinepyle.digest.job import send_digest_job

        _job_queue.run_once(
            send_digest_job, when=0, data=_chat_id, name="test_digest",
        )
        logger.info("Test digest triggered")
    else:
        logger.warning("Cannot trigger test digest: bot not connected")

    ctx = _base_context(request, active_tab="digest", test_sent=True)
    return templates.TemplateResponse("index.html", ctx)


# -----------------------------------------------------------------------
# Screen alert settings
# -----------------------------------------------------------------------


@app.get("/screens", response_class=HTMLResponse)
async def screens_page(request: Request):
    ctx = _base_context(request, active_tab="screens")
    return templates.TemplateResponse("index.html", ctx)


@app.post("/screens/save", response_class=HTMLResponse)
async def save_screen_settings(request: Request):
    form = await request.form()

    watched = list(form.getlist("watched_screens"))
    alerts_enabled = form.get("screen_alerts_enabled") == "true"
    interval = int(form.get("check_interval_minutes", "30") or "30")

    screen_settings = ScreenAlertSettings(
        watched_screens=[w for w in watched if w],
        alerts_enabled=alerts_enabled,
        check_interval_minutes=max(10, min(interval, 120)),
    )
    screen_settings.save()
    logger.info(
        "Screen alert settings saved: %d watched screens",
        len(screen_settings.watched_screens),
    )

    ctx = _base_context(request, active_tab="screens", screen_saved=True)
    ctx["screen_settings"] = screen_settings
    return templates.TemplateResponse("index.html", ctx)


# -----------------------------------------------------------------------
# Sync settings
# -----------------------------------------------------------------------


@app.get("/sync", response_class=HTMLResponse)
async def sync_page(request: Request):
    ctx = _base_context(request, active_tab="sync")
    return templates.TemplateResponse("index.html", ctx)


@app.post("/sync/save", response_class=HTMLResponse)
async def save_sync_settings(
    request: Request,
    sync_enabled: bool = Form(False),
    sync_interval_days: int = Form(1),
):
    sync_settings = SyncSettings(
        sync_enabled=sync_enabled,
        sync_interval_days=max(1, min(sync_interval_days, 30)),
    )
    sync_settings.save()
    logger.info(
        "Sync settings saved: enabled=%s, interval=%d days",
        sync_settings.sync_enabled,
        sync_settings.sync_interval_days,
    )

    ctx = _base_context(request, active_tab="sync", sync_saved=True)
    ctx["sync_settings"] = sync_settings
    return templates.TemplateResponse("index.html", ctx)


@app.post("/sync/trigger", response_class=HTMLResponse)
async def trigger_sync(request: Request):
    if _job_queue is not None:
        from cinepyle.theaters.sync_job import theater_sync_job

        _job_queue.run_once(
            theater_sync_job, when=0, data=_chat_id, name="manual_sync",
        )
        logger.info("Manual theater sync triggered")
    else:
        logger.warning("Cannot trigger sync: bot not connected")

    ctx = _base_context(request, active_tab="sync", sync_triggered=True)
    return templates.TemplateResponse("index.html", ctx)


# -----------------------------------------------------------------------
# Credentials settings (settings overlay)
# -----------------------------------------------------------------------


@app.post("/settings/credentials", response_class=HTMLResponse)
async def save_credentials(request: Request):
    form = await request.form()

    # Only update fields that are NOT set via env vars
    current = DigestSettings.load()

    llm_provider = form.get("llm_provider", current.llm_provider)
    llm_model = form.get("llm_model", current.llm_model)
    llm_api_key = form.get("llm_api_key", "")

    # Preserve existing API key if field was left empty (password field)
    if not llm_api_key and current.llm_api_key:
        llm_api_key = current.llm_api_key

    # Only save LLM settings if not overridden by env
    if not os.environ.get("LLM_PROVIDER"):
        current.llm_provider = llm_provider
    if not os.environ.get("LLM_MODEL"):
        current.llm_model = llm_model
    if not os.environ.get("LLM_API_KEY"):
        current.llm_api_key = llm_api_key

    current.save()
    logger.info("Credentials saved via dashboard")

    ctx = _base_context(request, active_tab="digest", saved=True)
    ctx["settings"] = current
    return templates.TemplateResponse("index.html", ctx)
