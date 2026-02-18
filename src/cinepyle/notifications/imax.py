"""IMAX screening notification service."""

import logging

from telegram.ext import ContextTypes

from cinepyle.scrapers.cgv import check_imax_screening

logger = logging.getLogger(__name__)

_notified_titles: set[str] = set()


async def check_imax_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: check for new IMAX screenings and notify."""
    chat_id = context.job.data

    try:
        result = check_imax_screening()
    except Exception:
        logger.exception("Failed to check IMAX screening")
        return

    if result is None:
        return

    title, booking_url = result

    if title in _notified_titles:
        return

    _notified_titles.add(title)

    text = f"🎬 CGV용산아이파크몰에서 [{title}] IMAX 상영이 시작되었습니다!"
    await context.bot.send_message(chat_id=chat_id, text=text)
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"예매하기: {booking_url}",
    )
    logger.info("IMAX notification sent: %s", title)
