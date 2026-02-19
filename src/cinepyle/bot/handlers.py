"""Telegram bot message handlers (NLP-based).

All text messages are routed through LLM intent classification.
Only /start is kept as a slash command (Telegram platform convention).
"""

import logging
from datetime import datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import ContextTypes

from cinepyle.bot.nlp import (
    ClassificationResult,
    Intent,
    classify_intent,
    classify_intent_fallback,
)
from cinepyle.config import KOBIS_API_KEY, resolve_llm
from cinepyle.theaters.finder import find_nearest_theaters

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start (first-time user greeting)."""
    await update.message.reply_text(
        "안녕하세요! 영화 알림봇이에요 🎬\n\n"
        "자연어로 편하게 말씀해주세요:\n"
        "• 저녁 7시 분당 영화 뭐해?\n"
        "• 영화 파묘에 누가 나와?\n"
        "• 박스오피스 순위 보여줘\n"
        "• 근처 영화관 찾아줘\n"
        "• CGV 예매하고 싶어\n"
        "• 선호 극장 CGV용산 추가해줘"
    )


async def message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle all text messages via LLM intent classification."""
    user_text = update.message.text
    if not user_text:
        return

    # Classify intent — resolve LLM credentials (env var > dashboard settings)
    provider, api_key, model = resolve_llm()

    if api_key:
        try:
            result = classify_intent(user_text, provider, api_key, model=model)
        except Exception:
            logger.exception("LLM classification failed, using keyword fallback")
            result = classify_intent_fallback(user_text)
    else:
        result = classify_intent_fallback(user_text)

    # Dispatch based on intent
    if result.intent == Intent.RANKING:
        await update.message.reply_text(result.reply)
        await _do_ranking(update)

    elif result.intent == Intent.NEARBY:
        await _do_nearby(update, result.reply)

    elif result.intent == Intent.THEATER_INFO:
        await update.message.reply_text(result.reply)
        await _do_theater_info(update, result.params.get("query", ""))

    elif result.intent == Intent.THEATER_LIST:
        await update.message.reply_text(result.reply)
        await _do_theater_list(
            update,
            chain=result.params.get("chain", ""),
            region=result.params.get("region", ""),
        )

    elif result.intent == Intent.NEW_MOVIES:
        await update.message.reply_text(result.reply)
        await _do_new_movies(update)

    elif result.intent == Intent.DIGEST:
        await update.message.reply_text(result.reply)
        await _do_digest(update)

    elif result.intent == Intent.BOOK:
        await _do_book(update, result)

    elif result.intent == Intent.SHOWTIME:
        await update.message.reply_text(result.reply)
        await _do_showtime(update, result.params)

    elif result.intent == Intent.MOVIE_INFO:
        await update.message.reply_text(result.reply)
        await _do_movie_info(update, result.params)

    elif result.intent == Intent.PREFERENCE:
        await _do_preference(update, result)

    elif result.intent == Intent.BOOKING_HISTORY:
        await update.message.reply_text(result.reply)
        await _do_booking_history(update, result.params)

    else:  # Intent.CHAT
        await update.message.reply_text(result.reply)


# ---------------------------------------------------------------------------
# Intent action handlers
# ---------------------------------------------------------------------------


async def _do_ranking(update: Update) -> None:
    """Fetch and send box office rankings."""
    from cinepyle.scrapers.boxoffice import fetch_box_office_with_fallback

    try:
        movies = await fetch_box_office_with_fallback(KOBIS_API_KEY)
    except Exception:
        logger.exception("Failed to fetch box office")
        await update.message.reply_text(
            "박스오피스 정보를 가져오는데 실패했습니다. 잠시 후 다시 시도해주세요."
        )
        return

    if not movies:
        await update.message.reply_text(
            "박스오피스 데이터를 가져올 수 없습니다.\n"
            "KOFIC_API_KEY를 설정하거나 잠시 후 다시 시도해주세요."
        )
        return

    lines = [f"{m['rank']}. {m['name']}" for m in movies]
    text = "🎬 일일 박스오피스 순위:\n\n" + "\n".join(lines)
    await update.message.reply_text(text)


async def _do_nearby(update: Update, reply: str) -> None:
    """Ask user to send their location."""
    location_button = KeyboardButton(text="📍 위치 전송", request_location=True)
    keyboard = ReplyKeyboardMarkup(
        [[location_button]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )
    await update.message.reply_text(reply, reply_markup=keyboard)


async def _do_theater_info(update: Update, query: str) -> None:
    """Search theater DB and show theater/screen details."""
    from cinepyle.theaters.models import SPECIAL_TYPES, TheaterDatabase

    if not query:
        await update.message.reply_text("어떤 극장을 찾으시나요? 극장 이름을 말씀해주세요.")
        return

    db = TheaterDatabase.load()
    try:
        matches = []
        q = query.lower()
        for t in db.theaters:
            if q in t.name.lower() or q in t.key.lower():
                matches.append(t)

        if not matches:
            await update.message.reply_text(
                f'"{query}" 검색 결과가 없습니다. 극장 이름을 다시 확인해주세요.'
            )
            return

        # Show up to 3 matches
        parts = []
        for t in matches[:3]:
            lines = [f"🏢 {t.name} ({t.chain})"]
            if t.address:
                lines.append(f"📍 {t.address}")

            total_seats = sum(s.seat_count for s in t.screens)
            lines.append(f"🎬 상영관 {len(t.screens)}개 (총 {total_seats:,}석)")

            special = [s for s in t.screens if s.screen_type in SPECIAL_TYPES]
            if special:
                type_names = _screen_type_labels(special)
                lines.append(f"⭐ 특수관: {', '.join(type_names)}")

            parts.append("\n".join(lines))

        text = "\n\n".join(parts)
        if len(matches) > 3:
            text += f"\n\n... 외 {len(matches) - 3}개 극장"

        await update.message.reply_text(text)
    finally:
        db.close()


def _screen_type_labels(screens: list) -> list[str]:
    """Convert screen objects to human-readable type labels (deduplicated)."""
    labels = {
        "imax": "IMAX",
        "4dx": "4DX",
        "screenx": "ScreenX",
        "dolby_atmos": "Dolby Atmos",
        "dolby_cinema": "Dolby Cinema",
        "superplex": "SuperPlex",
        "charlotte": "샤롯데",
        "comfort": "컴포트",
        "boutique": "부티크",
        "recliner": "리클라이너",
        "premium": "프리미엄",
    }
    seen = []
    for s in screens:
        label = labels.get(s.screen_type, s.screen_type)
        if label not in seen:
            seen.append(label)
    return seen


async def _do_theater_list(
    update: Update, chain: str = "", region: str = ""
) -> None:
    """List theaters filtered by chain and/or region."""
    from cinepyle.theaters.models import TheaterDatabase

    db = TheaterDatabase.load()
    try:
        if chain:
            theaters = db.get_by_chain(chain)
        else:
            theaters = db.theaters

        # Filter by region if specified
        if region:
            r = region.lower()
            theaters = [
                t for t in theaters if r in t.address.lower() or r in t.name.lower()
            ]

        if not theaters:
            msg = "조건에 맞는 극장이 없습니다."
            if chain:
                msg = f"{chain} 극장이 없습니다."
            await update.message.reply_text(msg)
            return

        # Group by chain
        by_chain: dict[str, list] = {}
        for t in theaters:
            by_chain.setdefault(t.chain, []).append(t)

        parts = []
        total = 0
        for c, ts in by_chain.items():
            total += len(ts)
            names = [t.name for t in ts[:20]]
            header = f"🎬 {c} ({len(ts)}개)"
            body = ", ".join(names)
            if len(ts) > 20:
                body += f" ... 외 {len(ts) - 20}개"
            parts.append(f"{header}\n{body}")

        text = f"🏢 극장 총 {total}개\n\n" + "\n\n".join(parts)

        # Telegram message limit
        if len(text) > 4096:
            text = text[:4090] + "\n..."

        await update.message.reply_text(text)
    finally:
        db.close()


async def _do_new_movies(update: Update) -> None:
    """Show recent movie releases."""
    from cinepyle.scrapers.kofic import fetch_recent_releases

    if not KOBIS_API_KEY:
        await update.message.reply_text(
            "최근 개봉작 조회는 KOFIC API 키가 필요합니다.\n"
            "KOFIC_API_KEY 환경변수를 설정해주세요."
        )
        return

    try:
        releases = fetch_recent_releases(KOBIS_API_KEY, days_back=7)
    except Exception:
        logger.exception("Failed to fetch recent releases")
        await update.message.reply_text(
            "최근 개봉작 정보를 가져오는데 실패했습니다. 잠시 후 다시 시도해주세요."
        )
        return

    if not releases:
        await update.message.reply_text("최근 7일 이내 개봉작이 없습니다.")
        return

    # Sort by open_date descending
    releases.sort(key=lambda m: m.get("open_date", ""), reverse=True)

    lines = ["🆕 최근 개봉 영화 (7일 이내):\n"]
    for m in releases[:15]:
        name = m.get("name", "")
        date = m.get("open_date", "")
        genre = m.get("genre", "")
        line = f"• {name}"
        if date:
            line += f" ({date})"
        if genre:
            line += f" — {genre}"
        lines.append(line)

    if len(releases) > 15:
        lines.append(f"\n... 외 {len(releases) - 15}편")

    await update.message.reply_text("\n".join(lines))


async def _do_digest(update: Update) -> None:
    """Scrape movie news and send digest."""
    from cinepyle.digest.formatter import format_digest_message, format_fallback_digest
    from cinepyle.digest.llm import get_provider
    from cinepyle.digest.scrapers import scrape_all

    settings = DigestSettings.load()

    try:
        articles = scrape_all(settings.sources_enabled)
    except Exception:
        logger.exception("Failed to scrape articles")
        await update.message.reply_text(
            "영화 뉴스를 가져오는데 실패했습니다. 잠시 후 다시 시도해주세요."
        )
        return

    if not articles:
        await update.message.reply_text("현재 가져올 수 있는 영화 뉴스가 없습니다.")
        return

    # LLM curation (with fallback)
    if settings.llm_api_key:
        try:
            provider = get_provider(settings.llm_provider, settings.llm_api_key)
            digest = provider.select_and_summarize(articles, settings.preferences)
            messages = format_digest_message(digest)
        except Exception:
            logger.exception("LLM digest curation failed, using fallback")
            messages = format_fallback_digest(articles)
    else:
        messages = format_fallback_digest(articles)

    for msg in messages:
        await update.message.reply_text(
            msg,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


# ---------------------------------------------------------------------------
# Booking URLs
# ---------------------------------------------------------------------------

# Mobile web URLs that open in-app when the app is installed
# (Android App Links / iOS Universal Links behaviour).
# If the app is not installed, the browser opens the login-aware web page.
_BOOKING_LINKS: dict[str, dict[str, str]] = {
    "CGV": {
        "label": "CGV 예매",
        # m.cgv.co.kr triggers the CGV app on mobile if installed
        "mobile": "https://m.cgv.co.kr/WebApp/MovieV4/movieList.aspx?mtype=now",
        "web": "https://cgv.co.kr/cnm/movieBook/cinema",
    },
    "롯데시네마": {
        "label": "롯데시네마 예매",
        "mobile": "https://www.lottecinema.co.kr/NLCHS/Ticketing",
        "web": "https://www.lottecinema.co.kr/NLCHS/Ticketing",
    },
    "메가박스": {
        "label": "메가박스 예매",
        "mobile": "https://m.megabox.co.kr/booking",
        "web": "https://www.megabox.co.kr/booking/timetable",
    },
}


async def _do_book(
    update: Update, result: ClassificationResult
) -> None:
    """Send booking deeplinks to the user.

    Provides mobile-first links (open in-app if installed) with
    web fallback.  When a specific chain is mentioned, only that
    chain's links are shown.
    """
    chain = result.params.get("chain", "")
    movie = result.params.get("movie", "")

    # Build header text
    text = result.reply or "예매 링크를 안내해드릴게요! 🎫"
    if movie:
        text += f"\n🎬 영화: {movie}"
    text += (
        "\n\n📱 앱이 설치되어 있으면 앱에서 열립니다.\n"
        "💡 예매 시 포인트/쿠폰이 있으면 결제 단계에서 적용 가능합니다."
    )

    await update.message.reply_text(text)

    # Determine which chains to show
    if chain and chain in _BOOKING_LINKS:
        chains_to_show = [chain]
    else:
        chains_to_show = list(_BOOKING_LINKS.keys())

    # Build inline keyboard: mobile link (primary) + web link
    buttons = []
    for c in chains_to_show:
        info = _BOOKING_LINKS[c]
        row = [
            InlineKeyboardButton(
                text=f"📱 {info['label']}",
                url=info["mobile"],
            ),
        ]
        # Add web link if different from mobile
        if info["web"] != info["mobile"]:
            row.append(
                InlineKeyboardButton(
                    text=f"🌐 {c} 웹",
                    url=info["web"],
                ),
            )
        buttons.append(row)

    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(
        "아래 버튼으로 예매하세요:",
        reply_markup=keyboard,
    )


# ---------------------------------------------------------------------------
# Showtime
# ---------------------------------------------------------------------------

_SCREEN_TYPE_LABEL: dict[str, str] = {
    "imax": "IMAX",
    "4dx": "4DX",
    "screenx": "ScreenX",
    "dolby_atmos": "Dolby Atmos",
    "dolby_cinema": "Dolby Cinema",
    "superplex": "SuperPlex",
    "charlotte": "샤롯데",
    "comfort": "컴포트",
    "boutique": "부티크",
    "recliner": "리클라이너",
    "premium": "프리미엄",
    "normal": "일반",
}

# Reverse mapping: user-facing label → internal type
_LABEL_TO_SCREEN_TYPE: dict[str, str] = {
    "imax": "imax",
    "아이맥스": "imax",
    "4dx": "4dx",
    "screenx": "screenx",
    "스크린x": "screenx",
    "돌비시네마": "dolby_cinema",
    "돌비 시네마": "dolby_cinema",
    "돌비": "dolby_cinema",
    "돌비애트모스": "dolby_atmos",
    "돌비 애트모스": "dolby_atmos",
    "샤롯데": "charlotte",
    "부티크": "boutique",
    "리클라이너": "recliner",
    "컴포트": "comfort",
    "프리미엄": "premium",
}


def _resolve_date(date_str: str):
    """Parse Korean date expressions into a date object."""
    import re
    from datetime import date, timedelta

    if not date_str:
        return date.today()

    d = date_str.strip()
    if d in ("오늘", "today"):
        return date.today()
    if d in ("내일", "tomorrow"):
        return date.today() + timedelta(days=1)
    if d in ("모레", "내일모레"):
        return date.today() + timedelta(days=2)

    # Try ISO format
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(d, fmt).date()
        except ValueError:
            pass

    # Try "2월 20일" pattern
    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", d)
    if m:
        from datetime import date as date_cls

        month, day = int(m.group(1)), int(m.group(2))
        return date_cls(date.today().year, month, day)

    return date.today()


def _parse_time_filter(time_str: str) -> str:
    """Parse Korean time expressions into HHMM format.

    Returns "" if empty or unparsable.
    """
    import re

    if not time_str:
        return ""

    t = time_str.strip()

    # "19:00" or "19시"
    m = re.search(r"(\d{1,2}):(\d{2})", t)
    if m:
        return f"{int(m.group(1)):02d}{int(m.group(2)):02d}"

    m = re.search(r"(\d{1,2})시\s*(\d{1,2})?분?", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        # Handle 오후/저녁 + small hour
        if ("오후" in t or "저녁" in t or "밤" in t) and hour < 12:
            hour += 12
        return f"{hour:02d}{minute:02d}"

    return ""


def _find_theaters_for_showtime(db, region: str, theater_query: str):
    """Find theaters matching region or specific theater name.

    Supports flexible matching: "용산 CGV" matches "CGV용산아이파크몰"
    by checking that all tokens in the query appear in the theater name
    or address (order-independent).
    """
    results = []

    search_terms = [s for s in [region, theater_query] if s]
    if not search_terms:
        return results

    for term in search_terms:
        # Split into tokens and remove whitespace
        tokens = [tok.lower() for tok in term.split() if tok]
        if not tokens:
            continue
        for t in db.theaters:
            if t in results:
                continue
            haystack = f"{t.name} {t.address}".lower()
            # All tokens must appear somewhere in name+address
            if all(tok in haystack for tok in tokens):
                results.append(t)

    return results


async def _do_showtime(update: Update, params: dict) -> None:
    """Fetch and display showtimes for a region/theater/time/movie."""
    from cinepyle.bot.theater_prefs import TheaterPreferences
    from cinepyle.theaters.models import TheaterDatabase
    from cinepyle.theaters.schedule import fetch_schedules_for_theaters

    region = params.get("region", "")
    time_str = params.get("time", "")
    date_str = params.get("date", "")
    movie_filter = params.get("movie", "")
    theater_query = params.get("theater", "")

    # Resolve date and time
    target_date = _resolve_date(date_str)
    min_time = _parse_time_filter(time_str)

    # If fallback mode, try to extract region from theater_query
    if not region and theater_query:
        region = theater_query

    # Find theaters
    db = TheaterDatabase.load()
    try:
        matched = _find_theaters_for_showtime(db, region, theater_query)
    finally:
        db.close()

    if not matched:
        await update.message.reply_text(
            f'"{region or theater_query}" 지역/극장을 찾을 수 없습니다.\n'
            "극장 이름이나 지역을 다시 확인해주세요."
        )
        return

    # Limit to 10 theaters to avoid rate limits
    matched = matched[:10]

    await update.message.reply_text(
        f"🔍 {len(matched)}개 극장 상영시간 조회 중..."
    )

    # Fetch schedules
    theaters_input = [(t.chain, t.theater_code, t.name) for t in matched]
    schedules = fetch_schedules_for_theaters(theaters_input, target_date)

    # Load preferences
    prefs = TheaterPreferences.load()
    pref_keys = set(prefs.preferred_theaters)
    pref_types = set(prefs.preferred_screen_types)

    # Sort: preferred theaters first
    schedules.sort(
        key=lambda s: (0 if f"{s.chain}:{s.theater_code}" in pref_keys else 1)
    )

    # Build output
    date_display = target_date.strftime("%Y-%m-%d")
    header = f"🎬 상영시간 ({date_display})"
    if region:
        header = f"🎬 {region} 상영시간 ({date_display})"

    parts = [header]

    for sched in schedules:
        if not sched.screenings and not sched.error:
            continue

        is_pref = f"{sched.chain}:{sched.theater_code}" in pref_keys
        theater_marker = " ⭐" if is_pref else ""
        theater_header = f"\n🏢 {sched.theater_name}{theater_marker}"

        if sched.error and not sched.screenings:
            parts.append(f"{theater_header}\n  ⚠️ {sched.error}")
            continue

        # Filter by time
        screenings = sched.screenings
        if min_time:
            screenings = [
                s for s in screenings
                if not s.start_time or s.start_time.replace(":", "") >= min_time
            ]

        # Filter by movie
        if movie_filter:
            mf = movie_filter.lower()
            screenings = [s for s in screenings if mf in s.movie_name.lower()]

        if not screenings:
            continue

        # Group by movie
        movies: dict[str, list] = {}
        for s in screenings:
            movies.setdefault(s.movie_name, []).append(s)

        lines = [theater_header]
        for movie_name, showings in movies.items():
            lines.append(f"  ▸ {movie_name}")
            # Sort by time, preferred screen types first
            showings.sort(
                key=lambda s: (
                    0 if s.screen_type in pref_types else 1,
                    s.start_time or "9999",
                )
            )
            # Deduplicate (same time + same screen)
            seen = set()
            for s in showings:
                key = (s.start_time, s.screen_id)
                if key in seen:
                    continue
                seen.add(key)

                screen_label = _SCREEN_TYPE_LABEL.get(s.screen_type, s.screen_name)
                pref_mark = " ⭐" if s.screen_type in pref_types else ""

                if s.start_time:
                    lines.append(
                        f"    {s.start_time} ({screen_label}) "
                        f"잔여 {s.remaining_seats}석{pref_mark}"
                    )
                else:
                    # CGV — no time info
                    lines.append(f"    ({screen_label}) 좌석 {s.remaining_seats}석{pref_mark}")

        if sched.error:
            lines.append(f"  ⚠️ {sched.error}")

        parts.append("\n".join(lines))

    if pref_keys or pref_types:
        parts.append("\n⭐ = 선호 극장/상영관")

    text = "\n".join(parts)
    if len(text) > 4096:
        text = text[:4090] + "\n..."

    await update.message.reply_text(text)


# ---------------------------------------------------------------------------
# Movie info
# ---------------------------------------------------------------------------


async def _do_movie_info(update: Update, params: dict) -> None:
    """Search movie and display detailed info from KOFIC."""
    from cinepyle.scrapers.kofic import fetch_movie_info, search_movie_by_name

    movie_name = params.get("movie", "")
    if not movie_name:
        await update.message.reply_text(
            "어떤 영화 정보를 찾으시나요? 영화 제목을 말씀해주세요."
        )
        return

    if not KOBIS_API_KEY:
        await update.message.reply_text(
            "영화 상세 정보 조회는 KOFIC API 키가 필요합니다.\n"
            "KOFIC_API_KEY 환경변수를 설정해주세요."
        )
        return

    try:
        matches = search_movie_by_name(KOBIS_API_KEY, movie_name)
    except Exception:
        logger.exception("KOFIC movie search failed")
        await update.message.reply_text(
            "영화 검색에 실패했습니다. 잠시 후 다시 시도해주세요."
        )
        return

    if not matches:
        await update.message.reply_text(
            f'"{movie_name}" 검색 결과가 없습니다. 영화 제목을 다시 확인해주세요.'
        )
        return

    # Fetch detail for best match
    top = matches[0]
    try:
        info = fetch_movie_info(KOBIS_API_KEY, top["code"])
    except Exception:
        logger.exception("KOFIC movie info failed")
        info = None

    if not info:
        # Fallback: show basic search result
        await update.message.reply_text(
            f"🎬 {top['name']}\n"
            f"개봉일: {top.get('open_date', '미정')}\n"
            f"장르: {top.get('genre', '정보 없음')}"
        )
        return

    lines = [f"🎬 {info['title']}"]
    if info.get("title_en"):
        lines.append(f"   ({info['title_en']})")
    if info.get("open_date"):
        lines.append(f"📅 개봉일: {info['open_date']}")
    if info.get("runtime"):
        lines.append(f"⏱ 러닝타임: {info['runtime']}분")
    if info.get("genres"):
        lines.append(f"🎭 장르: {', '.join(info['genres'])}")
    if info.get("rating"):
        lines.append(f"📋 등급: {info['rating']}")
    if info.get("directors"):
        lines.append(f"🎬 감독: {', '.join(info['directors'])}")
    if info.get("actors"):
        actor_parts = []
        for a in info["actors"][:10]:
            s = a["name"]
            if a.get("cast"):
                s += f" ({a['cast']}역)"
            actor_parts.append(s)
        lines.append(f"🎭 출연: {', '.join(actor_parts)}")
    if info.get("nations"):
        lines.append(f"🌍 제작국: {', '.join(info['nations'])}")

    await update.message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Preference management
# ---------------------------------------------------------------------------


async def _do_preference(update: Update, result: ClassificationResult) -> None:
    """Handle theater/screen preference management."""
    from cinepyle.bot.theater_prefs import TheaterPreferences
    from cinepyle.theaters.models import TheaterDatabase

    action = result.params.get("action", "list")
    theater_query = result.params.get("theater", "")
    screen_type_query = result.params.get("screen_type", "")

    prefs = TheaterPreferences.load()

    if action == "list":
        if not prefs.preferred_theaters and not prefs.preferred_screen_types:
            await update.message.reply_text(
                "설정된 선호 극장/상영관이 없습니다.\n\n"
                "예시:\n"
                "• 선호 극장 CGV용산 추가해줘\n"
                "• IMAX 선호 설정해줘"
            )
            return

        lines = ["⭐ 선호 설정:\n"]
        if prefs.preferred_theaters:
            db = TheaterDatabase.load()
            names = []
            for key in prefs.preferred_theaters:
                parts = key.split(":", 1)
                if len(parts) == 2:
                    t = db.get(parts[0], parts[1])
                    names.append(t.name if t else key)
                else:
                    names.append(key)
            db.close()
            lines.append(f"🏢 선호 극장: {', '.join(names)}")

        if prefs.preferred_screen_types:
            labels = [
                _SCREEN_TYPE_LABEL.get(st, st)
                for st in prefs.preferred_screen_types
            ]
            lines.append(f"🎬 선호 상영관: {', '.join(labels)}")

        await update.message.reply_text("\n".join(lines))
        return

    if action == "add":
        if theater_query:
            db = TheaterDatabase.load()
            match = _find_best_theater_match(db, theater_query)
            db.close()
            if match:
                key = f"{match.chain}:{match.theater_code}"
                if prefs.add_theater(key):
                    prefs.save()
                    await update.message.reply_text(
                        f"⭐ {match.name}을(를) 선호 극장에 추가했습니다."
                    )
                else:
                    await update.message.reply_text(
                        f"{match.name}은(는) 이미 선호 극장입니다."
                    )
            else:
                await update.message.reply_text(
                    f'"{theater_query}" 극장을 찾을 수 없습니다.'
                )
            return

        if screen_type_query:
            st = _LABEL_TO_SCREEN_TYPE.get(screen_type_query.lower())
            if st:
                if prefs.add_screen_type(st):
                    prefs.save()
                    await update.message.reply_text(
                        f"⭐ {_SCREEN_TYPE_LABEL.get(st, st)} 선호 설정 완료."
                    )
                else:
                    await update.message.reply_text(
                        f"{_SCREEN_TYPE_LABEL.get(st, st)}은(는) 이미 선호 상영관입니다."
                    )
            else:
                await update.message.reply_text(
                    f'"{screen_type_query}" 상영관 타입을 인식할 수 없습니다.'
                )
            return

    if action == "remove":
        if theater_query:
            db = TheaterDatabase.load()
            match = _find_best_theater_match(db, theater_query)
            db.close()
            if match:
                key = f"{match.chain}:{match.theater_code}"
                if prefs.remove_theater(key):
                    prefs.save()
                    await update.message.reply_text(
                        f"{match.name}을(를) 선호 극장에서 제거했습니다."
                    )
                else:
                    await update.message.reply_text(
                        f"{match.name}은(는) 선호 극장이 아닙니다."
                    )
            else:
                await update.message.reply_text(
                    f'"{theater_query}" 극장을 찾을 수 없습니다.'
                )
            return

        if screen_type_query:
            st = _LABEL_TO_SCREEN_TYPE.get(screen_type_query.lower())
            if st and prefs.remove_screen_type(st):
                prefs.save()
                await update.message.reply_text(
                    f"{_SCREEN_TYPE_LABEL.get(st, st)} 선호 설정을 제거했습니다."
                )
            return

    await update.message.reply_text(result.reply)


def _find_best_theater_match(db, query: str):
    """Find the single best theater match for a user query."""
    q = query.lower()
    for t in db.theaters:
        if q in t.name.lower():
            return t
    return None


# ---------------------------------------------------------------------------
# Booking history
# ---------------------------------------------------------------------------

_CHAIN_LABELS = {"cgv": "CGV", "lotte": "롯데시네마", "megabox": "메가박스"}


async def _do_booking_history(update: Update, params: dict) -> None:
    """Fetch and display booking history from cinema chains."""
    chain_filter = params.get("chain", "")

    await update.message.reply_text("🔍 예매 내역을 조회하고 있습니다... (잠시 기다려주세요)")

    try:
        from cinepyle.browser.booking_history import fetch_booking_history

        results = await fetch_booking_history(chain_filter)
    except ImportError:
        await update.message.reply_text(
            "예매 내역 기능을 사용하려면 Playwright를 설치해야 합니다.\n"
            "`playwright install chromium` 명령을 실행해주세요."
        )
        return
    except Exception:
        logger.exception("Booking history failed")
        await update.message.reply_text(
            "예매 내역 조회에 실패했습니다. 잠시 후 다시 시도해주세요."
        )
        return

    parts = ["📋 예매 내역\n"]
    has_records = False

    for result in results:
        if result.error:
            parts.append(f"⚠️ {_CHAIN_LABELS.get(result.chain, result.chain)}: {result.error}")
            continue

        if not result.records:
            label = _CHAIN_LABELS.get(result.chain, result.chain)
            parts.append(f"📭 {label}: 예매 내역이 없습니다")
            continue

        has_records = True
        label = _CHAIN_LABELS.get(result.chain, result.chain)
        parts.append(f"\n🎬 {label}")

        for rec in result.records[:10]:
            status_icon = {
                "confirmed": "✅",
                "cancelled": "❌",
                "watched": "🎞",
            }.get(rec.status, "📌")

            line = f"  {status_icon} {rec.movie_name}"
            if rec.date:
                line += f" ({rec.date})"
            if rec.theater_name:
                line += f"\n    📍 {rec.theater_name}"
            if rec.screen_name:
                line += f" {rec.screen_name}"
            if rec.time:
                line += f" {rec.time}"
            if rec.seats:
                line += f" [{', '.join(rec.seats)}]"
            parts.append(line)

        remaining = len(result.records) - 10
        if remaining > 0:
            parts.append(f"  ... 외 {remaining}건")

    text = "\n".join(parts)
    if len(text) > 4096:
        text = text[:4090] + "\n..."

    await update.message.reply_text(text)


# ---------------------------------------------------------------------------
# Location handler (unchanged)
# ---------------------------------------------------------------------------


async def location_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle location messages -- find nearby theaters."""
    location = update.message.location
    if location is None:
        return

    latitude = location.latitude
    longitude = location.longitude

    remove_keyboard = ReplyKeyboardRemove()
    await update.message.reply_text(
        "위치를 확인했습니다. 근처 영화관을 검색 중입니다...",
        reply_markup=remove_keyboard,
    )

    try:
        theaters = find_nearest_theaters(latitude, longitude, n=5)
    except Exception:
        logger.exception("Failed to find nearby theaters")
        await update.message.reply_text(
            "영화관 검색에 실패했습니다. 잠시 후 다시 시도해주세요."
        )
        return

    if not theaters:
        await update.message.reply_text("근처에 영화관을 찾을 수 없습니다.")
        return

    lines = []
    for i, t in enumerate(theaters, 1):
        lines.append(f"{i}. {t['TheaterName']} ({t['Chain']})")

    text = "📍 근처 영화관:\n\n" + "\n".join(lines)
    await update.message.reply_text(text)
