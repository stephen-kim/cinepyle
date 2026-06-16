"""Cinepyle bot entry point."""

import logging
from datetime import time as dt_time
from zoneinfo import ZoneInfo

from telegram.ext import Application
from telegram.request import HTTPXRequest

from cinepyle.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from cinepyle.digest.job import send_digest_job
from cinepyle.digest.settings import DigestSettings

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Build and run the scheduled Telegram news digest sender."""
    request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=10.0,
    )
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request)
        .build()
    )

    job_queue = app.job_queue

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

    logger.info("Telegram news digest sender starting...")
    app.run_polling(
        bootstrap_retries=5,
        allowed_updates=[],
    )


if __name__ == "__main__":
    main()
