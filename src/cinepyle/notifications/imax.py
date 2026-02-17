"""IMAX screening notification service.

Checks configured CGV theaters for new IMAX screenings and sends
Telegram notifications. Previously-notified titles are persisted
in SQLite so restarts don't cause duplicate alerts.

Dedup key format: "theater_name::movie_title" to distinguish the
same movie at different theaters.
"""

import logging

from telegram.ext import ContextTypes

from cinepyle.config import NOTIFICATION_DB_PATH
from cinepyle.notifications.store import NotificationStore
from cinepyle.scrapers.cgv import check_imax_screenings

logger = logging.getLogger(__name__)

_store: NotificationStore | None = None


def _get_store() -> NotificationStore:
    global _store
    if _store is None:
        _store = NotificationStore(NOTIFICATION_DB_PATH)
    return _store


async def check_imax_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: check for new IMAX screenings and notify."""
    chat_id = context.job.data

    try:
        results = await check_imax_screenings()
    except Exception:
        logger.exception("Failed to check IMAX screenings")
        return

    if not results:
        return

    store = _get_store()

    for title, booking_url, theater_name in results:
        # Composite dedup key: "theater_name::title"
        dedup_key = f"{theater_name}::{title}"

        if await store.is_imax_notified(dedup_key):
            continue

        await store.add_imax_title(dedup_key)

        text = f"🎬 {theater_name}에서 [{title}] IMAX 상영이 시작되었습니다!"
        await context.bot.send_message(chat_id=chat_id, text=text)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"예매하기: {booking_url}",
        )
        logger.info("IMAX notification sent: %s at %s", title, theater_name)
