"""New movie detection and notification service.

Detects movies newly entering the box office or recent releases,
enriches with Watcha expected ratings, and sends Telegram notifications.
Known movie codes are persisted in SQLite so restarts don't
re-trigger notifications.
"""

import logging
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from cinepyle.config import KOBIS_API_KEY, NOTIFICATION_DB_PATH, WATCHA_EMAIL, WATCHA_PASSWORD
from cinepyle.notifications.store import NotificationStore
from cinepyle.scrapers.boxoffice import fetch_daily_box_office
from cinepyle.scrapers.kofic import fetch_recent_releases
from cinepyle.scrapers.watcha import WatchaClient

logger = logging.getLogger(__name__)

_watcha_client: WatchaClient | None = None
_store: NotificationStore | None = None


def _get_watcha_client() -> WatchaClient:
    global _watcha_client
    if _watcha_client is None:
        _watcha_client = WatchaClient(WATCHA_EMAIL, WATCHA_PASSWORD)
    return _watcha_client


def _get_store() -> NotificationStore:
    global _store
    if _store is None:
        _store = NotificationStore(NOTIFICATION_DB_PATH)
    return _store


async def check_new_movies_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: detect new movies and notify with Watcha ratings."""
    chat_id = context.job.data

    # Gather movie codes from both box office and recent releases
    try:
        box_office = fetch_daily_box_office(KOBIS_API_KEY)
    except Exception:
        logger.exception("Failed to fetch box office data")
        box_office = []

    try:
        recent = fetch_recent_releases(KOBIS_API_KEY)
    except Exception:
        logger.exception("Failed to fetch recent releases")
        recent = []

    # Merge all movies by code
    all_movies: dict[str, dict] = {}
    for m in box_office:
        all_movies[m["code"]] = {
            "name": m["name"],
            "rank": m.get("rank"),
            "source": "boxoffice",
        }
    for m in recent:
        if m["code"] not in all_movies:
            all_movies[m["code"]] = {
                "name": m["name"],
                "open_date": m.get("open_date"),
                "genre": m.get("genre"),
                "source": "release",
            }

    current_codes = set(all_movies.keys())
    store = _get_store()
    known_codes = await store.get_known_movie_codes()

    if not known_codes:
        # First run ever: seed DB without sending notifications
        await store.add_movie_codes(current_codes)
        logger.info("Seeded known movies: %d entries", len(current_codes))
        return

    new_codes = current_codes - known_codes
    if not new_codes:
        return

    await store.add_movie_codes(new_codes)

    # Build notification with Watcha ratings and booking deeplinks
    watcha = _get_watcha_client()

    for code in new_codes:
        info = all_movies[code]
        name = info["name"]

        # Try to get Watcha expected rating
        try:
            rating = await watcha.get_expected_rating(name)
        except Exception:
            logger.exception("Watcha rating lookup failed for %s", name)
            rating = None

        # Build text
        text = f"\U0001f195 새 영화: {name}"
        if info.get("rank"):
            text += f" (박스오피스 {info['rank']}위)"
        if info.get("genre"):
            text += f"\n장르: {info['genre']}"
        if rating is not None:
            text += f"\n\u2b50 Watcha 예상 {rating}"

        # Booking deeplinks per chain (updated for 2025+ URLs)
        encoded_name = quote(name)
        buttons = [
            [
                InlineKeyboardButton(
                    text="CGV 예매",
                    url="https://cgv.co.kr/cnm/movieBook/cinema",
                ),
                InlineKeyboardButton(
                    text="롯데시네마 예매",
                    url="https://www.lottecinema.co.kr/NLCHS/Ticketing?filter=movie",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="메가박스 예매",
                    url="https://www.megabox.co.kr/booking/timetable",
                ),
            ],
        ]
        keyboard = InlineKeyboardMarkup(buttons)

        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
        )

    logger.info("New movie notification sent: %d movies", len(new_codes))
