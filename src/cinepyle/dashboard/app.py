"""FastAPI dashboard for digest, screen alert, and sync settings."""

import logging
import os
import re
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cinepyle.digest.settings import DigestSettings
from cinepyle.notifications.screen_settings import ScreenAlertSettings
from cinepyle.theaters.models import TheaterDatabase

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


def _sub_region_from_address(address: str, region: str) -> str:
    """Extract sub-region (구/시/군) from a Korean address string.

    Examples:
        서울특별시 강남구 ... → 강남구
        경기도 수원시 ...     → 수원시
        부산광역시 해운대구 ... → 해운대구
    """
    if not address:
        return "기타"
    addr = address.strip()

    # Metropolitan city (광역시) sub-regions: extract 구/군
    metro_prefixes = ("서울", "부산", "대구", "인천", "광주", "대전", "울산")
    for prefix in metro_prefixes:
        if addr.startswith(prefix):
            m = re.search(r"(\S+[구군])", addr[len(prefix):])
            return m.group(1) if m else "기타"

    # 세종 is a single metro with 읍/면/동 subdivisions
    if addr.startswith("세종"):
        m = re.search(r"(\S+[읍면동])", addr)
        return m.group(1) if m else "세종시"

    # Province (도) sub-regions: extract 시/군
    m = re.search(
        r"(?:경기도?|강원(?:특별자치)?도?|충청[남북]도|충[남북]|"
        r"전라[남북]도|전[남북]|전북특별자치도|경상[남북]도|경[남북]|"
        r"제주특별자치도|제주도?)\s*(\S+[시군])",
        addr,
    )
    if m:
        sub = m.group(1)
        # Normalize common variants (e.g. 고양특례시 → 고양시)
        sub = re.sub(r"특례시$", "시", sub)
        return sub

    # Fallback: try to find any 구/시/군
    m = re.search(r"(\S+[구시군])", addr)
    return m.group(1) if m else "기타"


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

    # Build region → sub_region → theaters nested mapping
    regions: dict[str, dict[str, list]] = {}
    for region_name in _REGION_ORDER:
        theaters_in_region = db.get_by_region(region_name)
        if not theaters_in_region:
            continue
        sub_regions: dict[str, list] = {}
        for theater in theaters_in_region:
            sub = _sub_region_from_address(theater.address, region_name)
            sub_regions.setdefault(sub, []).append(theater)
        # Sort sub-regions alphabetically, but put "기타" last
        sorted_subs: dict[str, list] = {}
        for key in sorted(sub_regions.keys(), key=lambda k: (k == "기타", k)):
            sorted_subs[key] = sub_regions[key]
        regions[region_name] = sorted_subs

    # Fallback: if no theaters have region data yet (pre-sync), group by chain
    if not regions:
        _CHAIN_LABELS = {
            "cgv": "CGV", "lotte": "롯데시네마",
            "megabox": "메가박스", "cineq": "씨네Q", "indie": "인디",
        }
        for chain_key, label in _CHAIN_LABELS.items():
            chain_theaters = chains.get(chain_key, [])
            if chain_theaters:
                regions[label] = {"전체": chain_theaters}

    last_sync_at = db.last_sync_at
    db.close()

    # Detect which env vars are set (for showing badge in UI)
    env_vars = {
        "LLM_PROVIDER": bool(os.environ.get("LLM_PROVIDER")),
        "LLM_MODEL": bool(os.environ.get("LLM_MODEL")),
        "LLM_API_KEY": bool(os.environ.get("LLM_API_KEY")),
        "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
        "ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "GEMINI_API_KEY": bool(os.environ.get("GEMINI_API_KEY")),
        "TELEGRAM_BOT_TOKEN": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
        "TELEGRAM_CHAT_ID": bool(os.environ.get("TELEGRAM_CHAT_ID")),
        "KOFIC_API_KEY": bool(os.environ.get("KOFIC_API_KEY")),
        "NAVER_MAPS_CLIENT_ID": bool(os.environ.get("NAVER_MAPS_CLIENT_ID")),
        "NAVER_MAPS_CLIENT_SECRET": bool(os.environ.get("NAVER_MAPS_CLIENT_SECRET")),
        "WATCHA_EMAIL": bool(os.environ.get("WATCHA_EMAIL")),
        "WATCHA_PASSWORD": bool(os.environ.get("WATCHA_PASSWORD")),
        "CGV_ID": bool(os.environ.get("CGV_ID")),
        "CGV_PASSWORD": bool(os.environ.get("CGV_PASSWORD")),
        "LOTTECINEMA_ID": bool(os.environ.get("LOTTECINEMA_ID")),
        "LOTTECINEMA_PASSWORD": bool(os.environ.get("LOTTECINEMA_PASSWORD")),
        "MEGABOX_ID": bool(os.environ.get("MEGABOX_ID")),
        "MEGABOX_PASSWORD": bool(os.environ.get("MEGABOX_PASSWORD")),
    }

    return {
        "request": request,
        "settings": DigestSettings.load(),
        "screen_settings": ScreenAlertSettings.load(),
        "chains": chains,
        "regions": regions,
        "last_sync_at": last_sync_at,
        "active_tab": active_tab,
        "env_vars": env_vars,
        "saved": False,
        "test_sent": False,
        "screen_saved": False,
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
# Credentials settings (settings overlay)
# -----------------------------------------------------------------------


@app.post("/settings/credentials", response_class=HTMLResponse)
async def save_credentials(request: Request):
    form = await request.form()

    # Only update fields that are NOT set via env vars
    current = DigestSettings.load()

    # Per-provider API keys and ordering
    provider_order = list(form.getlist("llm_provider_order"))
    if provider_order:
        current.llm_provider_order = provider_order

    _PROVIDER_ENV = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GEMINI_API_KEY",
    }
    api_keys = dict(current.llm_api_keys)
    for provider in ("openai", "anthropic", "google"):
        new_key = form.get(f"llm_api_key_{provider}", "")
        env_key = _PROVIDER_ENV.get(provider, "")
        if os.environ.get(env_key):
            continue  # skip if env overrides
        if new_key:
            api_keys[provider] = new_key
        # preserve existing if field left empty (password field)
    current.llm_api_keys = api_keys

    # Per-provider model overrides
    models = dict(current.llm_models)
    for provider in ("openai", "anthropic", "google"):
        model_val = form.get(f"llm_model_{provider}", "")
        models[provider] = model_val
    current.llm_models = models

    # Set primary provider to first in order (compat with old fields)
    if provider_order:
        current.llm_provider = provider_order[0]
        first_key = api_keys.get(provider_order[0], "")
        if first_key:
            current.llm_api_key = first_key
        first_model = models.get(provider_order[0], "")
        if first_model:
            current.llm_model = first_model

    current.save()
    logger.info("Credentials saved via dashboard")

    ctx = _base_context(request, active_tab="digest", saved=True)
    ctx["settings"] = current
    return templates.TemplateResponse("index.html", ctx)
