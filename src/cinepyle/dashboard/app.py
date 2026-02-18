"""FastAPI dashboard for digest settings."""

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cinepyle.digest.settings import DigestSettings

logger = logging.getLogger(__name__)

app = FastAPI(title="Cinepyle Dashboard")

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

# Reference to the bot's job_queue, set by main.py at startup
_job_queue = None
_chat_id: str = ""


def set_bot_context(job_queue, chat_id: str) -> None:
    """Store references so the dashboard can trigger test digests."""
    global _job_queue, _chat_id
    _job_queue = job_queue
    _chat_id = chat_id


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    settings = DigestSettings.load()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "settings": settings, "saved": False, "test_sent": False},
    )


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
    # Preserve existing API key if not changed
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
        llm_api_key=llm_api_key,
        preferences=preferences,
    )
    settings.save()
    logger.info("Digest settings saved")

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "settings": settings, "saved": True, "test_sent": False},
    )


@app.post("/test-digest", response_class=HTMLResponse)
async def test_digest(request: Request):
    """Trigger an immediate digest send for testing."""
    settings = DigestSettings.load()

    if _job_queue is not None:
        # Run the digest job via the bot's job queue
        from cinepyle.digest.job import send_digest_job

        _job_queue.run_once(
            send_digest_job,
            when=0,
            data=_chat_id,
            name="test_digest",
        )
        logger.info("Test digest triggered")
    else:
        logger.warning("Cannot trigger test digest: bot not connected")

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "settings": settings, "saved": False, "test_sent": True},
    )
