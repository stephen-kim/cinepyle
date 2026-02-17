"""Cinepyle bot entry point."""

import logging

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from cinepyle.bot.booking import build_booking_handlers
from cinepyle.bot.handlers import (
    help_command,
    location_handler,
    nearby_command,
    ranking_command,
    start_command,
)
from cinepyle.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from cinepyle.notifications.imax import check_imax_job
from cinepyle.notifications.new_movie import check_new_movies_job
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


def main() -> None:
    """Build and run the bot."""
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_shutdown(post_shutdown)
        .build()
    )

    # NLP booking handlers (returns [/book, callback, text_handler])
    booking_handlers = build_booking_handlers()

    # /book command (must be before generic text handler)
    app.add_handler(booking_handlers[0])

    # Command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ranking", ranking_command))
    app.add_handler(CommandHandler("nearby", nearby_command))

    # Location message handler
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))

    # Payment callback handler
    app.add_handler(booking_handlers[1])

    # NLP text catch-all (MUST be last — catches free-text booking intents)
    app.add_handler(booking_handlers[2])

    # Scheduled jobs
    job_queue = app.job_queue

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

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
