"""Telegram bot message handlers (NLP-based).

All text messages are routed through LLM intent classification.
Only /start is kept as a slash command (Telegram platform convention).
"""

import asyncio
import json
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

    # Load conversation history for follow-up recognition (last 5 turns)
    history: list[dict] = context.user_data.get("chat_history", [])

    # Classify intent — resolve LLM credentials (env var > dashboard settings)
    provider, api_key, model = resolve_llm()

    if api_key:
        try:
            result = classify_intent(
                user_text, provider, api_key, model=model, history=history,
            )
            # If LLM returned chat but keywords suggest a specific intent,
            # prefer the keyword match (LLM can be overly conservative with tool calls)
            if result.intent == Intent.CHAT:
                kw_result = classify_intent_fallback(user_text)
                if kw_result.intent != Intent.CHAT:
                    result = kw_result
            # LLM often returns nearby without chain/region params;
            # enrich from keyword fallback which extracts them reliably
            elif result.intent == Intent.NEARBY:
                kw_result = classify_intent_fallback(user_text)
                if kw_result.intent == Intent.NEARBY and kw_result.params:
                    for k, v in kw_result.params.items():
                        if v and not result.params.get(k):
                            result.params[k] = v
        except Exception:
            logger.exception("LLM classification failed, using keyword fallback")
            result = classify_intent_fallback(user_text)
    else:
        result = classify_intent_fallback(user_text)

    # Store conversation turn (user message + bot reply) for future context
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": result.reply})
    # Keep last 5 turns (10 messages) to avoid token bloat
    context.user_data["chat_history"] = history[-10:]

    # Dispatch based on intent
    if result.intent == Intent.RANKING:
        await update.message.reply_text(result.reply)
        await _do_ranking(update)

    elif result.intent == Intent.NEARBY:
        await _do_nearby(update, context, result)

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

    elif result.intent == Intent.SEAT_MAP:
        await update.message.reply_text(result.reply)
        await _do_seat_map(update, result.params)

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


async def _do_nearby(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    result: ClassificationResult,
) -> None:
    """Find nearby theaters — via GPS location or text-based region search.

    Stores ``chain_filter`` in user_data so the subsequent location_handler
    can filter by chain (e.g. "근처 메가박스").
    """
    chain = result.params.get("chain", "")
    region = result.params.get("region", "")

    # Store chain filter for location_handler
    context.user_data["nearby_chain_filter"] = chain

    # If a region/address was provided, search by text immediately
    if region:
        await _search_nearby_by_text(update, region, chain)
        return

    # Otherwise ask for GPS location
    location_button = KeyboardButton(text="📍 위치 전송", request_location=True)
    keyboard = ReplyKeyboardMarkup(
        [[location_button]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )
    await update.message.reply_text(result.reply, reply_markup=keyboard)


async def _search_nearby_by_text(
    update: Update, region: str, chain: str = ""
) -> None:
    """Search theaters by region text (e.g. 신림, 강남)."""
    from cinepyle.theaters.models import TheaterDatabase

    db = TheaterDatabase.load()
    try:
        matches = []
        r = region.lower()
        for t in db.theaters:
            haystack = f"{t.name} {t.address}".lower()
            if r not in haystack:
                continue
            if chain:
                cf = chain.lower()
                if cf not in t.chain.lower() and cf not in t.name.lower():
                    continue
            matches.append(t)

        if not matches:
            chain_text = f" {chain}" if chain else ""
            await update.message.reply_text(
                f'"{region}" 근처{chain_text} 영화관을 찾을 수 없습니다.\n'
                "📍 위치를 전송하시면 GPS로 검색할 수 있어요!"
            )
            return

        # Sort by name for readability (no GPS = can't sort by distance)
        matches = matches[:10]
        lines = []
        for i, t in enumerate(matches, 1):
            line = f"{i}. {t.name} ({t.chain})"
            if t.address:
                line += f"\n   📍 {t.address}"
            lines.append(line)

        chain_text = f" {chain}" if chain else ""
        text = f'📍 "{region}" 근처{chain_text} 영화관:\n\n' + "\n".join(lines)
        await update.message.reply_text(text)
    finally:
        db.close()


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


def _match_movie_title(query: str, titles: set[str]) -> set[str]:
    """Match user's movie query against actual screening titles.

    Uses LLM for fuzzy matching (typos, spacing, transliteration).
    Falls back to simple substring matching without spaces.
    Returns the set of matched original title strings.
    """
    # 1) Try LLM matching
    provider, api_key, model = resolve_llm()
    if api_key:
        try:
            return _llm_match_movie(query, titles, provider, api_key, model)
        except Exception:
            logger.exception("LLM movie matching failed, using fallback")

    # 2) Fallback: space-stripped substring
    q = query.replace(" ", "").lower()
    return {t for t in titles if q in t.replace(" ", "").lower()}


def _llm_match_movie(
    query: str, titles: set[str], provider: str, api_key: str, model: str,
) -> set[str]:
    """Ask LLM to pick matching movie titles from a list."""
    import json as _json

    titles_list = sorted(titles)
    prompt = (
        "아래 영화 제목 목록에서 사용자가 찾는 영화와 일치하는 제목을 모두 골라줘.\n"
        "오타, 띄어쓰기 차이, 외래어 표기 차이를 감안해서 판단해.\n"
        "일치하는 제목이 없으면 빈 배열을 반환해.\n\n"
        f"사용자 검색어: {query}\n\n"
        f"영화 목록:\n" + "\n".join(f"- {t}" for t in titles_list) + "\n\n"
        'JSON 형식으로만 응답: {"matches": ["제목1", "제목2"]}'
    )

    if provider == "openai":
        import openai
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model or "gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = _json.loads(resp.choices[0].message.content)
    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model or "claude-3-5-haiku-latest",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _json.loads(resp.content[0].text)
    elif provider == "google":
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        gen_model = genai.GenerativeModel(model or "gemini-2.0-flash")
        resp = gen_model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json", temperature=0,
            ),
        )
        raw = _json.loads(resp.text)
    else:
        return set()

    matches = raw.get("matches", [])
    # Only return titles that actually exist in our set
    return {t for t in matches if t in titles}


# Generic words to ignore when matching theater searches
_NOISE_WORDS = {
    "영화관", "극장", "시네마", "cinema", "theater", "theatre",
    "근처", "주변", "에서", "있는", "오늘", "내일", "상영",
}

# Keywords meaning "all theaters nationwide"
_NATIONWIDE_WORDS = {"전국", "전체", "아무데나", "어디든", "전부"}


def _find_theaters_for_showtime(db, region: str, theater_query: str):
    """Find theaters matching region or specific theater name.

    Supports flexible matching: "용산 CGV" matches "CGV용산아이파크몰"
    by checking that all tokens in the query appear in the theater name
    or address (order-independent). Generic words like "영화관" are ignored.
    """
    results = []

    search_terms = [s for s in [region, theater_query] if s]
    if not search_terms:
        return results

    for term in search_terms:
        # Split into tokens, remove noise words
        tokens = [
            tok.lower() for tok in term.split()
            if tok and tok not in _NOISE_WORDS
        ]
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
    screen_type_filter = params.get("screen_type", "")

    # Resolve date and time
    target_date = _resolve_date(date_str)
    min_time = _parse_time_filter(time_str)

    # Check if user wants nationwide search
    all_terms = " ".join(s for s in [region, theater_query] if s)
    is_nationwide = any(w in all_terms for w in _NATIONWIDE_WORDS)

    # Nationwide without movie filter is too broad
    if is_nationwide and not movie_filter:
        await update.message.reply_text(
            "전국 검색은 영화 제목과 함께 알려줘!\n"
            "(예: 인터스텔라 전국 상영관)"
        )
        return

    # If fallback mode, try to extract region from theater_query
    if not is_nationwide and not region and theater_query:
        region = theater_query

    # Find theaters
    db = TheaterDatabase.load()
    try:
        if is_nationwide:
            # Use now_playing DB for fast lookup
            all_movie_names = db.get_now_playing_movies()

            if all_movie_names:
                matched_movies = _match_movie_title(movie_filter, all_movie_names)
                if matched_movies:
                    # Find theaters playing the matched movies
                    seen_keys: set[tuple[str, str]] = set()
                    matched = []
                    for movie in matched_movies:
                        for np in db.find_theaters_playing(movie):
                            key = (np.chain, np.theater_code)
                            if key not in seen_keys:
                                seen_keys.add(key)
                                t = db.get(np.chain, np.theater_code)
                                if t:
                                    matched.append(t)
                else:
                    db.close()
                    await update.message.reply_text(
                        f"'{movie_filter}' 상영 정보를 찾을 수 없습니다."
                    )
                    return
            else:
                # now_playing empty — fallback to all theaters with screens
                matched = [t for t in db.theaters if t.screens]
        else:
            matched = _find_theaters_for_showtime(db, region, theater_query)

            # No region/theater specified → use preferred theaters
            if not matched and not region and not theater_query:
                prefs = TheaterPreferences.load()
                if prefs.preferred_theaters:
                    pref_set = set(prefs.preferred_theaters)
                    for t in db.theaters:
                        if t.key in pref_set:
                            matched.append(t)
    finally:
        db.close()

    if not matched:
        if not region and not theater_query:
            await update.message.reply_text(
                "어느 극장에서 보려고 해? 지역이나 극장 이름을 알려줘!\n"
                "(예: 강남, CGV용산, 목동 롯데시네마)"
            )
        else:
            await update.message.reply_text(
                f'"{region or theater_query}" 지역/극장을 찾을 수 없습니다.\n'
                "극장 이름이나 지역을 다시 확인해주세요."
            )
        return

    # Limit theaters (nationwide uses all matched; regional caps at 10)
    if not is_nationwide:
        matched = matched[:10]

    if is_nationwide:
        await update.message.reply_text(
            f"🔍 전국 {len(matched)}개 극장에서 '{movie_filter}' 검색 중... (잠시 기다려주세요)"
        )
    else:
        await update.message.reply_text(
            f"🔍 {len(matched)}개 극장 상영시간 조회 중..."
        )

    # Fetch schedules (include Lotte meta for correct composite ID)
    theaters_input = [
        (t.chain, t.theater_code, t.name, json.loads(t.meta or "{}"))
        for t in matched
    ]
    schedules = fetch_schedules_for_theaters(theaters_input, target_date)

    # Load preferences
    prefs = TheaterPreferences.load()
    pref_keys = set(prefs.preferred_theaters)
    pref_types = set(prefs.preferred_screen_types)

    # Sort: preferred theaters first
    schedules.sort(
        key=lambda s: (0 if f"{s.chain}:{s.theater_code}" in pref_keys else 1)
    )

    # Resolve movie filter via LLM if available
    matched_titles: set[str] | None = None
    if movie_filter:
        all_titles = set()
        for sched in schedules:
            for s in sched.screenings:
                all_titles.add(s.movie_name)
        if all_titles:
            matched_titles = _match_movie_title(movie_filter, all_titles)

    # Build output
    date_display = target_date.strftime("%Y-%m-%d")
    screen_label = ""
    if screen_type_filter:
        st = _LABEL_TO_SCREEN_TYPE.get(screen_type_filter.lower(), "")
        screen_label = _SCREEN_TYPE_LABEL.get(st, screen_type_filter.upper())
    header = f"🎬 상영시간 ({date_display})"
    if region and screen_label:
        header = f"🎬 {region} {screen_label} 상영시간 ({date_display})"
    elif region:
        header = f"🎬 {region} 상영시간 ({date_display})"
    elif screen_label:
        header = f"🎬 {screen_label} 상영시간 ({date_display})"

    parts = [header]

    for sched in schedules:
        if not sched.screenings and not sched.error:
            continue

        is_pref = f"{sched.chain}:{sched.theater_code}" in pref_keys
        theater_marker = " ⭐" if is_pref else ""
        theater_header = f"\n🏢 {sched.theater_name}{theater_marker}"

        if sched.error and not sched.screenings:
            # Skip error-only theaters in nationwide search (too noisy)
            if is_nationwide:
                continue
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
        if matched_titles is not None:
            screenings = [
                s for s in screenings if s.movie_name in matched_titles
            ]

        # Filter by screen type (IMAX, 4DX, etc.)
        if screen_type_filter:
            st = _LABEL_TO_SCREEN_TYPE.get(screen_type_filter.lower(), "")
            if st:
                screenings = [
                    s for s in screenings if s.screen_type == st
                ]

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

    # Check if we found any actual showings
    if len(parts) <= 1:
        # Only header, no theater results
        no_result = header
        if movie_filter:
            no_result += f"\n\n'{movie_filter}' 상영 정보를 찾을 수 없습니다."
        else:
            no_result += "\n\n상영 정보를 찾을 수 없습니다."
        if min_time:
            no_result += f"\n(시간 필터: {min_time[:2]}:{min_time[2:]} 이후)"
        await update.message.reply_text(no_result)
        return

    if pref_keys or pref_types:
        parts.append("\n⭐ = 선호 극장/상영관")

    text = "\n".join(parts)
    if len(text) > 4096:
        text = text[:4090] + "\n..."

    await update.message.reply_text(text)


# ---------------------------------------------------------------------------
# Seat map
# ---------------------------------------------------------------------------


async def _do_seat_map(update: Update, params: dict) -> None:
    """Capture and send a seat map screenshot for a specific showtime."""
    from io import BytesIO

    from cinepyle.theaters.models import TheaterDatabase
    from cinepyle.theaters.schedule import fetch_schedules_for_theaters

    region = params.get("region", "")
    time_str = params.get("time", "")
    date_str = params.get("date", "")
    movie_filter = params.get("movie", "")
    theater_query = params.get("theater", "")

    target_date = _resolve_date(date_str)
    min_time = _parse_time_filter(time_str)

    # Find theaters
    db = TheaterDatabase.load()
    try:
        matched = _find_theaters_for_showtime(db, region, theater_query)
    finally:
        db.close()

    if not matched:
        await update.message.reply_text(
            "극장을 찾을 수 없습니다. 극장 이름이나 지역을 알려줘!\n"
            "(예: CGV용산 인터스텔라 7시 좌석 보여줘)"
        )
        return

    matched = matched[:5]  # limit for performance

    # Fetch schedules
    theaters_input = [
        (t.chain, t.theater_code, t.name, json.loads(t.meta or "{}"))
        for t in matched
    ]
    schedules = fetch_schedules_for_theaters(theaters_input, target_date)

    # Resolve movie filter
    matched_titles: set[str] | None = None
    if movie_filter:
        all_titles = set()
        for sched in schedules:
            for s in sched.screenings:
                all_titles.add(s.movie_name)
        if all_titles:
            matched_titles = _match_movie_title(movie_filter, all_titles)

    # Find best matching screening
    best_screening = None
    best_schedule = None
    for sched in schedules:
        for s in sched.screenings:
            if matched_titles is not None and s.movie_name not in matched_titles:
                continue
            if min_time and s.start_time:
                if s.start_time.replace(":", "") < min_time:
                    continue
            if best_screening is None:
                best_screening = s
                best_schedule = sched
            elif min_time and s.start_time and best_screening.start_time:
                # Prefer closest time match
                if abs(int(s.start_time.replace(":", "")) - int(min_time)) < abs(
                    int(best_screening.start_time.replace(":", "")) - int(min_time)
                ):
                    best_screening = s
                    best_schedule = sched

    if not best_screening or not best_schedule:
        await update.message.reply_text(
            "해당 조건에 맞는 상영을 찾을 수 없습니다.\n"
            "극장, 영화, 시간을 다시 확인해주세요."
        )
        return

    # Loading message
    await update.message.reply_text(
        f"🔍 {best_schedule.theater_name} - {best_screening.movie_name} "
        f"{best_screening.start_time} 좌석 배치도를 가져오는 중... (10-20초 소요)"
    )

    # Capture seat map
    try:
        from cinepyle.browser.seat_map import capture_seat_map

        meta = json.loads(
            next(
                (t.meta for t in matched if t.theater_code == best_schedule.theater_code),
                "{}",
            )
            or "{}"
        )

        seat_result = await capture_seat_map(
            chain=best_schedule.chain,
            theater_code=best_schedule.theater_code,
            theater_name=best_schedule.theater_name,
            movie_name=best_screening.movie_name,
            start_time=best_screening.start_time,
            screen_id=best_screening.screen_id,
            screen_name=best_screening.screen_name,
            date_str=best_schedule.date,
            remaining_seats=best_screening.remaining_seats,
            meta=meta,
            schedule_id=best_screening.schedule_id,
        )
    except ImportError:
        await update.message.reply_text(
            "좌석 배치도 기능을 사용하려면 Playwright를 설치해야 합니다.\n"
            "`playwright install chromium`"
        )
        return
    except Exception:
        logger.exception("Seat map capture failed")
        seat_result = None

    # Send photo or fallback to text
    if seat_result and seat_result.success and seat_result.screenshot:
        caption = (
            f"🎬 {best_screening.movie_name}\n"
            f"🏢 {best_schedule.theater_name} {best_screening.screen_name}\n"
            f"⏰ {best_screening.start_time} | 잔여 {best_screening.remaining_seats}석"
        )
        await update.message.reply_photo(
            photo=BytesIO(seat_result.screenshot),
            caption=caption,
        )
    else:
        error_msg = seat_result.error if seat_result else "좌석 배치도를 가져올 수 없습니다"
        await update.message.reply_text(
            f"⚠️ {error_msg}\n\n"
            f"📊 텍스트 정보:\n"
            f"🎬 {best_screening.movie_name}\n"
            f"🏢 {best_schedule.theater_name} {best_screening.screen_name}\n"
            f"⏰ {best_screening.start_time}\n"
            f"💺 잔여 좌석: {best_screening.remaining_seats}석"
        )


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
    """Handle location messages — find nearby theaters.

    Uses the local TheaterDatabase (no HTTP calls) so results are instant.
    If a ``nearby_chain_filter`` was stored by ``_do_nearby``, it filters
    by that chain (e.g. only MegaBox results).
    """
    logger.info("location_handler called")
    location = update.message.location
    if location is None:
        logger.warning("location_handler: location is None")
        return

    latitude = location.latitude
    longitude = location.longitude
    logger.info("Location received: lat=%s, lon=%s", latitude, longitude)

    # Retrieve chain filter set by _do_nearby (if any)
    chain_filter = context.user_data.pop("nearby_chain_filter", "")

    remove_keyboard = ReplyKeyboardRemove()
    await update.message.reply_text(
        "위치를 확인했습니다. 근처 영화관을 검색 중입니다...",
        reply_markup=remove_keyboard,
    )

    try:
        theaters = find_nearest_theaters(
            latitude, longitude, n=5, chain_filter=chain_filter,
        )
    except Exception:
        logger.exception("Failed to find nearby theaters")
        await update.message.reply_text(
            "영화관 검색에 실패했습니다. 잠시 후 다시 시도해주세요."
        )
        return

    if not theaters:
        chain_text = f" {chain_filter}" if chain_filter else ""
        await update.message.reply_text(
            f"근처에{chain_text} 영화관을 찾을 수 없습니다."
        )
        return

    lines = []
    for i, t in enumerate(theaters, 1):
        lines.append(f"{i}. {t['TheaterName']} ({t['Chain']})")

    chain_text = f" {chain_filter}" if chain_filter else ""
    text = f"📍 근처{chain_text} 영화관:\n\n" + "\n".join(lines)
    await update.message.reply_text(text)
