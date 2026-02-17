"""Cinepyle bot entry point.

Runs the Telegram bot and FastAPI dashboard concurrently
on the same asyncio event loop.
"""

import asyncio
import logging
from datetime import time as dt_time
from zoneinfo import ZoneInfo

import uvicorn
from telegram.ext import Application, CommandHandler

from cinepyle.bot.booking import build_booking_handlers
from cinepyle.bot.handlers import (
    help_command,
    nearby_command,
    ranking_command,
    start_command,
)
from cinepyle.config import (
    DASHBOARD_PORT,
    SETTINGS_DB_PATH,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from cinepyle.dashboard.app import app as fastapi_app
from cinepyle.dashboard.settings_manager import SettingsManager
from cinepyle.notifications.daily_digest import daily_digest_job
from cinepyle.notifications.new_movie import check_new_movies_job
from cinepyle.notifications.screen_monitor import check_screens_job
from cinepyle.notifications.theater_sync import load_seed_theaters, sync_theaters_job
from cinepyle.scrapers.browser import close_browser

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_shutdown(application: Application) -> None:
    """Shut down the shared Playwright browser on bot exit."""
    logger.info("Shutting down browser...")
    await close_browser()


async def async_main() -> None:
    """Async entry point: run Telegram bot + FastAPI dashboard concurrently."""
    # 1. Initialise settings manager
    settings = await SettingsManager.create(SETTINGS_DB_PATH)

    # 2. Build Telegram Application
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_shutdown(post_shutdown)
        .build()
    )
    settings.set_telegram_app(app)

    # 3. Register handlers
    booking_handlers = build_booking_handlers()

    app.add_handler(booking_handlers[0])  # /book command

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ranking", ranking_command))
    app.add_handler(CommandHandler("nearby", nearby_command))

    app.add_handler(booking_handlers[1])  # Location handler
    app.add_handler(booking_handlers[2])  # Payment callback handler
    app.add_handler(booking_handlers[3])  # NLP text catch-all (MUST be last)

    # 4. Scheduled jobs (intervals from settings, fallback to defaults)
    job_queue = app.job_queue

    screen_interval = int(settings.get("screen_check_interval", "600"))
    job_queue.run_repeating(
        check_screens_job,
        interval=screen_interval,
        first=10,
        data=TELEGRAM_CHAT_ID,
        name="screen_monitor",
    )

    new_movie_interval = int(settings.get("new_movie_check_interval", "3600"))
    job_queue.run_repeating(
        check_new_movies_job,
        interval=new_movie_interval,
        first=5,
        data=TELEGRAM_CHAT_ID,
        name="new_movie_check",
    )

    KST = ZoneInfo("Asia/Seoul")
    job_queue.run_daily(
        daily_digest_job,
        time=dt_time(hour=9, minute=0, tzinfo=KST),
        data=TELEGRAM_CHAT_ID,
        name="daily_digest",
    )

    # Theater list sync — daily at 4 AM + once on startup if cache empty
    job_queue.run_daily(
        sync_theaters_job,
        time=dt_time(hour=4, minute=0, tzinfo=KST),
        data=TELEGRAM_CHAT_ID,
        name="theater_sync",
    )
    if not settings.get_cached_theater_list():
        # Load bundled seed data immediately for first-run search
        seed = load_seed_theaters()
        if seed:
            await settings.sync_theater_list(seed)
            logger.info("Loaded %d seed theaters into DB", len(seed))
        # Then schedule a full sync (including API data) shortly after
        job_queue.run_once(
            sync_theaters_job, when=30, data=TELEGRAM_CHAT_ID,
            name="theater_sync_init",
        )

    # 5. Run Telegram bot + FastAPI dashboard concurrently
    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=DASHBOARD_PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)

    logger.info("Bot starting (dashboard on port %d)...", DASHBOARD_PORT)

    async with app:
        await app.start()
        await app.updater.start_polling()

        try:
            await server.serve()
        finally:
            logger.info("Shutting down...")
            await app.updater.stop()
            await app.stop()
            await settings.close()


def main() -> None:
    """Build and run the bot."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
