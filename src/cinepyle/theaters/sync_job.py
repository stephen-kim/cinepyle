"""Scheduled job for theater & screen sync."""

import asyncio
import logging

from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def theater_sync_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: sync all theater+screen data."""
    from cinepyle.theaters.sync import sync_all_theaters

    chat_id = context.job.data

    try:
        db = await asyncio.to_thread(sync_all_theaters)
        total_theaters = len(db.theaters)
        total_screens = sum(len(t.screens) for t in db.theaters)
        logger.info(
            "Theater sync complete: %d theaters, %d screens",
            total_theaters,
            total_screens,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🔄 극장 동기화 완료\n"
                f"극장 {total_theaters}개 · 상영관 {total_screens}개"
            ),
        )
    except Exception:
        logger.exception("Theater sync job failed")
