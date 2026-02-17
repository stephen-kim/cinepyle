"""Universal screen/theater monitoring notification service.

Replaces the old IMAX-only monitor. Checks user-configured monitor
targets (whole theaters or specific screens) for new movies and sends
Telegram notifications. Dedup keys are persisted in SQLite.

Dedup key format: "theater_name::screen_name::movie_title"
  - For "all" monitors: "theater_name::*::movie_title"
"""

import logging

from telegram.ext import ContextTypes

from cinepyle.config import NOTIFICATION_DB_PATH
from cinepyle.notifications.store import NotificationStore
from cinepyle.scrapers.screens import fetch_screens

logger = logging.getLogger(__name__)

_store: NotificationStore | None = None


def _get_store() -> NotificationStore:
    global _store
    if _store is None:
        _store = NotificationStore(NOTIFICATION_DB_PATH)
    return _store


async def check_screens_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: check all screen monitors for new movies and notify."""
    chat_id = context.job.data

    try:
        from cinepyle.dashboard.settings_manager import SettingsManager

        mgr = SettingsManager.get_instance()
        monitors = mgr.get_screen_monitors()
    except Exception:
        logger.exception("Failed to load screen monitors")
        return

    if not monitors:
        return

    store = _get_store()

    for monitor in monitors:
        chain_key = monitor.get("chain_key", "")
        theater_code = monitor.get("theater_code", "")
        theater_name = monitor.get("theater_name", "")
        screen_filter = monitor.get("screen_filter", "all")

        if not chain_key or not theater_name:
            continue

        try:
            schedules = await fetch_screens(chain_key, theater_code)
        except Exception:
            logger.exception(
                "Screen fetch failed for %s (%s)", theater_name, chain_key
            )
            continue

        if not schedules:
            continue

        # Apply screen filter
        if screen_filter != "all":
            schedules = [
                s for s in schedules if screen_filter in s.screen_name
            ]

        # Deduplicate by movie title per monitor target
        # (multiple showtimes for same movie on same screen → single alert)
        seen_movies: set[str] = set()
        for s in schedules:
            if screen_filter == "all":
                dedup_key = f"{theater_name}::*::{s.movie_title}"
            else:
                dedup_key = f"{theater_name}::{s.screen_name}::{s.movie_title}"

            # Skip if we already processed this movie in this run
            movie_key = f"{screen_filter}::{s.movie_title}"
            if movie_key in seen_movies:
                continue
            seen_movies.add(movie_key)

            if await store.is_screen_notified(dedup_key):
                continue

            await store.add_screen_notified(dedup_key)

            # Build notification message
            if screen_filter == "all":
                emoji = "🏢"
                text = f"{emoji} {theater_name}에서 [{s.movie_title}] 상영이 시작되었습니다!"
            else:
                emoji = "🎥"
                text = (
                    f"{emoji} {theater_name} {s.screen_name}에서 "
                    f"[{s.movie_title}] 상영이 시작되었습니다!"
                )

            if s.format_tags:
                text += f"\n🏷 {', '.join(s.format_tags)}"

            try:
                await context.bot.send_message(chat_id=chat_id, text=text)
                logger.info(
                    "Screen notification sent: %s at %s (%s)",
                    s.movie_title,
                    theater_name,
                    s.screen_name,
                )
            except Exception:
                logger.exception("Failed to send screen notification")
