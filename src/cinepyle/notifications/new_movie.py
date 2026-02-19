"""New movie detection and notification service."""

import logging
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from cinepyle.config import KOBIS_API_KEY, WATCHA_EMAIL, WATCHA_PASSWORD
from cinepyle.scrapers.kofic import fetch_recent_releases
from cinepyle.scrapers.watcha import WatchaClient

logger = logging.getLogger(__name__)

_known_movie_codes: set[str] = set()
_watcha_client: WatchaClient | None = None


def _get_watcha_client() -> WatchaClient | None:
    global _watcha_client
    if not WATCHA_EMAIL or not WATCHA_PASSWORD:
        return None
    if _watcha_client is None:
        _watcha_client = WatchaClient(WATCHA_EMAIL, WATCHA_PASSWORD)
    return _watcha_client


async def check_new_movies_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: detect new movies and notify with Watcha ratings."""
    chat_id = context.job.data

    # Gather movie codes from box office (with Watcha fallback)
    from cinepyle.scrapers.boxoffice import fetch_box_office_with_fallback

    try:
        box_office = await fetch_box_office_with_fallback(KOBIS_API_KEY)
    except Exception:
        logger.exception("Failed to fetch box office data")
        box_office = []

    # Recent releases only available with KOFIC key
    recent: list[dict] = []
    if KOBIS_API_KEY:
        try:
            recent = fetch_recent_releases(KOBIS_API_KEY)
        except Exception:
            logger.exception("Failed to fetch recent releases")

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

    if not _known_movie_codes:
        # First run: seed without sending notifications
        _known_movie_codes.update(current_codes)
        logger.info("Seeded known movies: %d entries", len(_known_movie_codes))
        return

    new_codes = current_codes - _known_movie_codes
    if not new_codes:
        return

    _known_movie_codes.update(new_codes)

    # Build notification with Watcha ratings and booking deeplinks
    watcha = _get_watcha_client()

    for code in new_codes:
        info = all_movies[code]
        name = info["name"]

        # Try to get Watcha expected rating (skip if not configured)
        rating = None
        if watcha is not None:
            try:
                rating = watcha.get_expected_rating(name)
            except Exception:
                logger.exception("Watcha rating lookup failed for %s", name)
                rating = None

        # Build text
        text = f"🆕 새 영화: {name}"
        if info.get("rank"):
            text += f" (박스오피스 {info['rank']}위)"
        if info.get("genre"):
            text += f"\n장르: {info['genre']}"
        if rating is not None:
            text += f"\n⭐ Watcha 예상 {rating}"

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
