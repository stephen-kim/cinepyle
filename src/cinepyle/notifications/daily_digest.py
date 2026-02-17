"""Daily movie digest notification service.

Sends a daily summary at 9:00 AM KST containing:
- Upcoming releases (next 2 weeks) with Watcha expected ratings
- Daily box office TOP 10 with ratings
- Cine21 and Naver Movie search links for each movie
"""

import html
import logging
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from telegram.ext import ContextTypes

from cinepyle.config import KOBIS_API_KEY, WATCHA_EMAIL, WATCHA_PASSWORD
from cinepyle.scrapers.boxoffice import fetch_daily_box_office
from cinepyle.scrapers.kofic import fetch_upcoming_releases
from cinepyle.scrapers.watcha import WatchaClient

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
MAX_WATCHA_UPCOMING = 3
MAX_WATCHA_BOXOFFICE = 5
TELEGRAM_MSG_LIMIT = 4000

_watcha_client: WatchaClient | None = None


def _get_watcha_client() -> WatchaClient:
    global _watcha_client
    if _watcha_client is None:
        _watcha_client = WatchaClient(WATCHA_EMAIL, WATCHA_PASSWORD)
    return _watcha_client


def _cine21_search_url(name: str) -> str:
    return f"http://www.cine21.com/search/?q={quote(name)}"


def _naver_movie_url(name: str) -> str:
    return f"https://search.naver.com/search.naver?query={quote(name + ' \uc601\ud654')}"


def _format_date_short(open_date: str) -> str:
    clean = open_date.replace("-", "")
    if len(clean) < 8:
        return open_date
    return f"{int(clean[4:6])}/{int(clean[6:8])}"


async def _enrich_with_ratings(movies: list[dict], max_lookups: int) -> None:
    watcha = _get_watcha_client()
    for movie in movies[:max_lookups]:
        try:
            movie["rating"] = await watcha.get_expected_rating(movie["name"])
        except Exception:
            logger.exception("Watcha lookup failed for %s", movie["name"])
            movie["rating"] = None


def _build_upcoming_section(upcoming: list[dict]) -> str:
    if not upcoming:
        return ""

    lines = ["<b>\u2501\u2501 \U0001f4c5 \uac1c\ubd09 \uc608\uc815 (2\uc8fc \uc774\ub0b4) \u2501\u2501</b>"]
    for m in upcoming:
        dt = _format_date_short(m["open_date"])
        nm = html.escape(m["name"])
        genre = f" ({html.escape(m['genre'])})" if m.get("genre") else ""
        c21 = _cine21_search_url(m["name"])
        nv = _naver_movie_url(m["name"])

        lines.append(f"\u2022 {dt} <b>{nm}</b>{genre}")
        if m.get("rating") is not None:
            lines.append(f"  \u2b50 Watcha \uc608\uc0c1 {m['rating']}")
        lines.append(f'  \U0001f517 <a href="{c21}">\uc528\ub12421</a> | <a href="{nv}">\ub124\uc774\ubc84</a>')

    return "\n".join(lines)


def _build_boxoffice_section(box_office: list[dict]) -> str:
    if not box_office:
        return ""

    lines = ["<b>\u2501\u2501 \U0001f3c6 \ubc15\uc2a4\uc624\ud53c\uc2a4 TOP 10 \u2501\u2501</b>"]
    for m in box_office:
        nm = html.escape(m["name"])
        rating = f" \u2b50 {m['rating']}" if m.get("rating") else ""
        c21 = _cine21_search_url(m["name"])
        nv = _naver_movie_url(m["name"])
        lines.append(f'{m["rank"]}. <a href="{nv}">{nm}</a>{rating} (<a href="{c21}">\uc528\ub12421</a>)')

    return "\n".join(lines)


async def daily_digest_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.job.data
    today = datetime.now(KST).strftime("%Y-%m-%d")

    # 1. Fetch data (each source independent)
    try:
        upcoming = fetch_upcoming_releases(KOBIS_API_KEY, days_ahead=14)
    except Exception:
        logger.exception("Daily digest: failed to fetch upcoming releases")
        upcoming = []

    try:
        box_office = fetch_daily_box_office(KOBIS_API_KEY)
    except Exception:
        logger.exception("Daily digest: failed to fetch box office")
        box_office = []

    if not upcoming and not box_office:
        logger.warning("Daily digest: no data available, skipping")
        return

    # 2. Enrich with Watcha ratings (limited to avoid slow Playwright lookups)
    await _enrich_with_ratings(upcoming, MAX_WATCHA_UPCOMING)
    await _enrich_with_ratings(box_office, MAX_WATCHA_BOXOFFICE)

    # 3. Build message
    header = f"<b>\U0001f3ac \uc624\ub298\uc758 \uc601\ud654 \ub2e4\uc774\uc81c\uc2a4\ud2b8</b> ({today})"
    upcoming_section = _build_upcoming_section(upcoming)
    boxoffice_section = _build_boxoffice_section(box_office)

    parts = [header]
    if upcoming_section:
        parts.append(upcoming_section)
    if boxoffice_section:
        parts.append(boxoffice_section)

    full_text = "\n\n".join(parts)

    # 4. Send (split if exceeding Telegram limit)
    if len(full_text) <= TELEGRAM_MSG_LIMIT:
        await context.bot.send_message(
            chat_id=chat_id,
            text=full_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        if upcoming_section:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{header}\n\n{upcoming_section}",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        if boxoffice_section:
            await context.bot.send_message(
                chat_id=chat_id,
                text=boxoffice_section,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

    logger.info(
        "Daily digest sent: %d upcoming, %d box office",
        len(upcoming),
        len(box_office),
    )
