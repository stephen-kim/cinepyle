"""Screen alert notification service.

Periodically checks schedules for user-watched screens and sends
Telegram notifications when a new movie appears.

Dedup: in-memory set backed by JSON for restart survival.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import requests

from telegram.ext import ContextTypes

from cinepyle.notifications.screen_settings import ScreenAlertSettings
from cinepyle.theaters.models import TheaterDatabase

logger = logging.getLogger(__name__)

SEEN_PATH = Path("config/screen_alerts_seen.json")

_seen_keys: set[str] = set()
_initialized: bool = False


def _load_seen() -> None:
    global _seen_keys, _initialized
    if SEEN_PATH.exists():
        try:
            data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
            _seen_keys = set(data.get("seen", []))
        except (json.JSONDecodeError, TypeError):
            _seen_keys = set()
    _initialized = True


def _save_seen() -> None:
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    trimmed = sorted(_seen_keys)[-2000:]
    SEEN_PATH.write_text(
        json.dumps({"seen": trimmed}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _make_key(chain: str, theater_code: str, screen_id: str, movie: str) -> str:
    return f"{chain}:{theater_code}:{screen_id}:{movie}"


# ---------------------------------------------------------------------------
# Schedule fetchers (return {screen_id: [movie_title, ...]})
# ---------------------------------------------------------------------------


def _fetch_cgv_schedule(theater_code: str) -> dict[str, list[str]]:
    """Fetch CGV schedule for a theater → {scnsNo: [movie, ...]}."""
    from cinepyle.theaters.sync import _cgv_get

    today = datetime.now().strftime("%Y%m%d")
    result: dict[str, list[str]] = {}
    try:
        data = _cgv_get(
            "/cnm/atkt/searchMovScnInfo",
            f"coCd=A420&siteNo={theater_code}&scnYmd={today}&rtctlScopCd=01",
        )
        if not data:
            return result
        # API wraps in {"statusCode": 0, "data": [...]}
        raw = data.get("data", data)
        items = (
            raw
            if isinstance(raw, list)
            else raw.get("list", raw.get("movieScnList", []))
        )
        for item in items:
            scns_no = str(item.get("scnsNo", ""))
            movie = item.get("movNm", "")
            if scns_no and movie:
                result.setdefault(scns_no, [])
                if movie not in result[scns_no]:
                    result[scns_no].append(movie)
    except Exception:
        logger.debug("CGV schedule fetch failed for %s", theater_code)
    return result


def _fetch_lotte_schedule(theater_code: str) -> dict[str, list[str]]:
    """Fetch Lotte Cinema schedule → {screen_key: [movie, ...]}."""
    from cinepyle.theaters.sync import _lotte_api, LOTTE_TICKETING_URL

    today = datetime.now().strftime("%Y-%m-%d")
    result: dict[str, list[str]] = {}

    # We need the composite ID. Try common patterns.
    # The watched screen key has theater_code = cinemaID (numeric).
    # Lotte composite ID is "divisionCode|sortSequence|cinemaID".
    # We'll try "1|1|{cinemaID}" as the most common pattern.
    composite_ids = [f"1|1|{theater_code}", f"1|2|{theater_code}"]

    for composite_id in composite_ids:
        try:
            sched = _lotte_api(
                LOTTE_TICKETING_URL,
                MethodName="GetPlaySequence",
                playDate=today,
                cinemaID=composite_id,
                representationMovieCode="",
            )

            movie_names: dict[str, str] = {}
            for entry in sched.get("PlaySeqsHeader", {}).get("Items", []):
                movie_names[entry.get("MovieCode", "")] = entry.get(
                    "MovieNameKR", "",
                )

            for entry in sched.get("PlaySeqs", {}).get("Items", []):
                screen_name = entry.get("ScreenNameKR", "")
                screen_div = str(entry.get("ScreenDivisionCode", "100"))
                screen_key = f"{screen_div}_{screen_name}"
                movie_code = entry.get("MovieCode", "")
                title = movie_names.get(movie_code, "")
                if screen_key and title:
                    result.setdefault(screen_key, [])
                    if title not in result[screen_key]:
                        result[screen_key].append(title)

            if result:
                break  # found data with this composite ID
        except Exception:
            logger.debug(
                "Lotte schedule failed for %s (%s)", theater_code, composite_id,
            )
    return result


def _fetch_megabox_schedule(brch_no: str) -> dict[str, list[str]]:
    """Fetch MegaBox schedule → {theabNo: [movie, ...]}."""
    today = datetime.now().strftime("%Y%m%d")
    result: dict[str, list[str]] = {}
    try:
        resp = requests.post(
            "https://www.megabox.co.kr/on/oh/ohc/Brch/schedulePage.do",
            data={
                "masterType": "brch",
                "brchNo": brch_no,
                "brchNo1": brch_no,
                "firstAt": "Y",
                "playDe": today,
            },
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.megabox.co.kr/"},
            timeout=10,
        )
        data = resp.json()
        for entry in data.get("megaMap", {}).get("movieFormList", []):
            theab_no = str(entry.get("theabNo", ""))
            title = entry.get("movieNm", "")
            if theab_no and title:
                result.setdefault(theab_no, [])
                if title not in result[theab_no]:
                    result[theab_no].append(title)
    except Exception:
        logger.debug("MegaBox schedule failed for %s", brch_no)
    return result


# ---------------------------------------------------------------------------
# Main check job
# ---------------------------------------------------------------------------

_FETCHERS: dict[str, callable] = {
    "cgv": _fetch_cgv_schedule,
    "lotte": _fetch_lotte_schedule,
    "megabox": _fetch_megabox_schedule,
}


async def check_screen_alerts_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: check watched screens for new movies and notify."""
    global _initialized

    chat_id = context.job.data

    if not _initialized:
        _load_seen()

    settings = ScreenAlertSettings.load()
    if not settings.alerts_enabled or not settings.watched_screens:
        return

    db = TheaterDatabase.load()

    # Group watches by (chain, theater_code)
    watches: dict[tuple[str, str], list[str]] = {}
    for screen_key in settings.watched_screens:
        parts = screen_key.split(":", 2)
        if len(parts) != 3:
            continue
        chain, theater_code, screen_id = parts
        watches.setdefault((chain, theater_code), []).append(screen_id)

    new_alerts: list[tuple[str, str, str]] = []  # (theater_name, screen_name, movie)

    for (chain, theater_code), screen_ids in watches.items():
        theater = db.get(chain, theater_code)
        if theater is None:
            continue

        fetcher = _FETCHERS.get(chain)
        if fetcher is None:
            continue

        try:
            screen_movies = fetcher(theater_code)
        except Exception:
            logger.debug("Schedule fetch failed for %s:%s", chain, theater_code)
            continue

        for screen_id in screen_ids:
            movies = screen_movies.get(screen_id, [])

            # Fuzzy match: try to find the screen by name if exact ID doesn't work
            if not movies:
                screen_obj = next(
                    (s for s in theater.screens if s.screen_id == screen_id),
                    None,
                )
                if screen_obj:
                    for sched_key, sched_movies in screen_movies.items():
                        if (
                            screen_obj.name in sched_key
                            or sched_key in screen_obj.name
                        ):
                            movies = sched_movies
                            break

            # Resolve display name
            screen_display = screen_id
            screen_obj = next(
                (s for s in theater.screens if s.screen_id == screen_id),
                None,
            )
            if screen_obj:
                screen_display = screen_obj.name

            for title in movies:
                seen_key = _make_key(chain, theater_code, screen_id, title)
                if seen_key in _seen_keys:
                    continue
                _seen_keys.add(seen_key)
                new_alerts.append((theater.name, screen_display, title))

    if not new_alerts:
        return

    for theater_name, screen_name, movie_title in new_alerts:
        text = (
            f"🎬 <b>{theater_name}</b> — {screen_name}\n"
            f"새 상영: <b>{movie_title}</b>"
        )
        try:
            await context.bot.send_message(
                chat_id=chat_id, text=text, parse_mode="HTML",
            )
        except Exception:
            logger.exception("Failed to send screen alert")

    _save_seen()
    logger.info("Screen alerts: %d new notifications", len(new_alerts))
