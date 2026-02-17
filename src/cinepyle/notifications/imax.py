"""IMAX screening notification service.

Checks CGV용산아이파크몰 for new IMAX screenings and sends
Telegram notifications. Previously-notified titles are persisted
in SQLite so restarts don't cause duplicate alerts.
"""

import logging

from telegram.ext import ContextTypes

from cinepyle.config import NOTIFICATION_DB_PATH
from cinepyle.notifications.store import NotificationStore
from cinepyle.scrapers.cgv import check_imax_screening

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
        result = await check_imax_screening()
    except Exception:
        logger.exception("Failed to check IMAX screening")
        return

    if result is None:
        return

    title, booking_url = result
    store = _get_store()

    if await store.is_imax_notified(title):
        return

    await store.add_imax_title(title)

    text = f"🎬 CGV용산아이파크몰에서 [{title}] IMAX 상영이 시작되었습니다!"
    await context.bot.send_message(chat_id=chat_id, text=text)
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"예매하기: {booking_url}",
    )
    logger.info("IMAX notification sent: %s", title)
