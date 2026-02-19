"""Cinepyle bot entry point."""

import logging
import threading
from datetime import time as dt_time
from zoneinfo import ZoneInfo

import uvicorn
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from cinepyle.config import DASHBOARD_PORT, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from cinepyle.bot.handlers import location_handler, message_handler, start_command
from cinepyle.dashboard.app import app as dashboard_app
from cinepyle.dashboard.app import set_bot_context
from cinepyle.digest.job import send_digest_job
from cinepyle.digest.settings import DigestSettings
from cinepyle.notifications.imax import check_imax_job
from cinepyle.notifications.new_movie import check_new_movies_job
from cinepyle.notifications.screen_alert import check_screen_alerts_job
from cinepyle.notifications.screen_settings import ScreenAlertSettings

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


def main() -> None:
    """Build and run the bot."""
    # Start dashboard in background
    dashboard_thread = threading.Thread(target=_run_dashboard, daemon=True)
    dashboard_thread.start()
    logger.info("Dashboard started on port %d", DASHBOARD_PORT)

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # /start for first-time users (Telegram sends this automatically)
    app.add_handler(CommandHandler("start", start_command))

    # All text messages go through NLP intent classification
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # Location messages (for nearby theater flow)
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

    # Register BrowserManager shutdown (cleanup Playwright if used)
    async def _shutdown_browser(application) -> None:
        try:
            from cinepyle.browser.manager import BrowserManager

            mgr = BrowserManager._instance
            if mgr is not None:
                await mgr.shutdown()
                logger.info("BrowserManager shut down")
        except ImportError:
            pass
        except Exception:
            logger.exception("BrowserManager shutdown error")

    app.post_shutdown = _shutdown_browser

    # Send startup greeting to Telegram (with now_playing stats)
    async def _send_startup_greeting(application) -> None:
        try:
            from cinepyle.theaters.models import TheaterDatabase

            db = TheaterDatabase.load()
            total_theaters = len(db.theaters)
            now_playing_movies = db.get_now_playing_movies()
            synced_at = db.last_sync_at
            db.close()

            text = "🎬 Cinepyle 봇이 시작되었습니다!"
            if now_playing_movies:
                text += (
                    f"\n\n📊 극장 {total_theaters}개 | "
                    f"상영 중 영화 {len(now_playing_movies)}편"
                )
            if synced_at:
                # Show KST time
                from datetime import datetime, timezone
                try:
                    utc_dt = datetime.fromisoformat(synced_at)
                    kst_dt = utc_dt.astimezone(ZoneInfo("Asia/Seoul"))
                    text += f"\n🕐 데이터 기준: {kst_dt.strftime('%m/%d %H:%M')} KST"
                except Exception:
                    pass

            await application.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=text,
            )
        except Exception:
            logger.warning("Failed to send startup greeting (TELEGRAM_CHAT_ID may be invalid)")

    app.post_init = _send_startup_greeting

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
