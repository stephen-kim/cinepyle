"""Cinepyle bot entry point."""

import logging
import threading
from datetime import datetime, time as dt_time, timezone
from zoneinfo import ZoneInfo

import uvicorn
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from cinepyle.config import DASHBOARD_PORT, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from cinepyle.bot.handlers import (
    help_command,
    location_handler,
    nearby_command,
    ranking_command,
    start_command,
)
from cinepyle.dashboard.app import app as dashboard_app
from cinepyle.dashboard.app import set_bot_context
from cinepyle.digest.job import send_digest_job
from cinepyle.digest.settings import DigestSettings
from cinepyle.notifications.imax import check_imax_job
from cinepyle.notifications.new_movie import check_new_movies_job
from cinepyle.notifications.screen_alert import check_screen_alerts_job
from cinepyle.notifications.screen_settings import ScreenAlertSettings
from cinepyle.theaters.models import TheaterDatabase
from cinepyle.theaters.sync_job import theater_sync_job
from cinepyle.theaters.sync_settings import SyncSettings

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _run_dashboard() -> None:
    """Run the FastAPI dashboard in a background thread."""
    uvicorn.run(
        dashboard_app,
        host="0.0.0.0",
        port=DASHBOARD_PORT,
        log_level="warning",
    )


def _seconds_until_sync(sync_settings: SyncSettings) -> int | None:
    """Calculate seconds until next sync is needed.

    Returns 30 (startup delay) if sync is overdue, or seconds until
    the interval expires.  Returns None if sync is disabled.
    """
    if not sync_settings.sync_enabled:
        return None

    interval_secs = sync_settings.sync_interval_days * 86400

    db = TheaterDatabase.load()
    last = db.last_sync_at
    db.close()

    if not last:
        # Never synced — run soon after startup
        return 30

    try:
        last_dt = datetime.fromisoformat(last)
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
        remaining = interval_secs - elapsed
        if remaining <= 0:
            return 30  # overdue
        return int(remaining)
    except (ValueError, TypeError):
        return 30


def main() -> None:
    """Build and run the bot."""
    # Start dashboard in background
    dashboard_thread = threading.Thread(target=_run_dashboard, daemon=True)
    dashboard_thread.start()
    logger.info("Dashboard started on port %d", DASHBOARD_PORT)

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ranking", ranking_command))
    app.add_handler(CommandHandler("nearby", nearby_command))

    # Location message handler
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))

    # Scheduled jobs
    job_queue = app.job_queue

    # Give dashboard access to the job queue for test-digest
    set_bot_context(job_queue, TELEGRAM_CHAT_ID)

    # IMAX check: every 30 seconds
    job_queue.run_repeating(
        check_imax_job,
        interval=30,
        first=10,
        data=TELEGRAM_CHAT_ID,
        name="imax_check",
    )

    # New movie check: every hour
    job_queue.run_repeating(
        check_new_movies_job,
        interval=3600,
        first=5,
        data=TELEGRAM_CHAT_ID,
        name="new_movie_check",
    )

    # Daily digest
    KST = ZoneInfo("Asia/Seoul")
    settings = DigestSettings.load()
    if settings.schedule_enabled:
        job_queue.run_daily(
            send_digest_job,
            time=dt_time(
                hour=settings.schedule_hour,
                minute=settings.schedule_minute,
                tzinfo=KST,
            ),
            data=TELEGRAM_CHAT_ID,
            name="daily_digest",
        )
        logger.info(
            "Daily digest scheduled at %02d:%02d KST",
            settings.schedule_hour,
            settings.schedule_minute,
        )

    # Theater & screen sync: configurable interval (default 1 day)
    sync_settings = SyncSettings.load()
    first_sync = _seconds_until_sync(sync_settings)
    if first_sync is not None:
        interval_secs = sync_settings.sync_interval_days * 86400
        job_queue.run_repeating(
            theater_sync_job,
            interval=interval_secs,
            first=first_sync,
            data=TELEGRAM_CHAT_ID,
            name="theater_sync",
        )
        logger.info(
            "Theater sync scheduled every %d day(s), first in %d sec",
            sync_settings.sync_interval_days,
            first_sync,
        )
    else:
        logger.info("Theater sync disabled")

    # Screen alert check
    screen_settings = ScreenAlertSettings.load()
    if screen_settings.alerts_enabled:
        job_queue.run_repeating(
            check_screen_alerts_job,
            interval=screen_settings.check_interval_minutes * 60,
            first=120,  # 2 min after startup (after initial sync)
            data=TELEGRAM_CHAT_ID,
            name="screen_alert_check",
        )
        logger.info(
            "Screen alerts scheduled every %d min",
            screen_settings.check_interval_minutes,
        )

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
