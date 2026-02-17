"""Unified screen-level schedule scraper for all cinema chains.

Fetches per-screen (hall) schedules from each chain's API,
returning structured data that includes the screen/hall name
and format tags. Used by the screen monitor notification job
and the dashboard screen-select UI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


@dataclass
class ScreenSchedule:
    """A single showtime entry with screen/hall metadata."""

    screen_name: str  # "IMAX 1관", "돌비시네마", "3관"
    movie_title: str  # Korean movie title
    start_time: str  # "14:30"
    format_tags: list[str] = field(default_factory=list)  # ["IMAX", "2D"]


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


async def fetch_screens(
    chain_key: str, theater_code: str
) -> list[ScreenSchedule]:
    """Fetch screen-level schedule for a theater.

    Returns a list of ScreenSchedule entries grouped by screen/hall.
    """
    if chain_key == "megabox":
        return _fetch_megabox_screens(theater_code)
    elif chain_key == "lotte":
        return _fetch_lotte_screens(theater_code)
    elif chain_key == "cgv":
        return await _fetch_cgv_screens(theater_code)
    elif chain_key == "cineq":
        return _fetch_cineq_screens(theater_code)
    return []


def fetch_screen_names(
    chain_key: str, theater_code: str
) -> list[str]:
    """Return unique screen/hall names for a theater (for UI selection).

    Synchronous — suitable for wrapping with asyncio.to_thread().
    """
    if chain_key == "megabox":
        return _get_megabox_screen_names(theater_code)
    elif chain_key == "lotte":
        return _get_lotte_screen_names(theater_code)
    elif chain_key == "cgv":
        # CGV requires async Playwright — handled separately
        return []
    elif chain_key == "cineq":
        return _get_cineq_screen_names(theater_code)
    return []


# ------------------------------------------------------------------
# Megabox
# ------------------------------------------------------------------

_MEGA_URL = "https://www.megabox.co.kr/on/oh/ohc/Brch/schedulePage.do"


def _megabox_raw_schedule(theater_code: str) -> list[dict]:
    """Fetch raw movieFormList from Megabox API."""
    today = datetime.now().strftime("%Y%m%d")
    res = requests.post(
        _MEGA_URL,
        data={
            "masterType": "brch",
            "brchNo": theater_code,
            "brchNo1": theater_code,
            "firstAt": "Y",
            "playDe": today,
        },
        timeout=15,
    ).json()
    return res.get("megaMap", {}).get("movieFormList", [])


def _fetch_megabox_screens(theater_code: str) -> list[ScreenSchedule]:
    """Parse Megabox API response into ScreenSchedule entries."""
    try:
        items = _megabox_raw_schedule(theater_code)
    except Exception:
        logger.exception("Megabox schedule fetch failed for %s", theater_code)
        return []

    results: list[ScreenSchedule] = []
    for item in items:
        screen_name = item.get("theabExpoNm", "").strip()
        movie_title = item.get("movieNm", "").strip()
        start_time = item.get("playStartTime", "").strip()

        if not screen_name or not movie_title:
            continue

        tags: list[str] = []
        play_kind = item.get("playKindNm", "")
        if play_kind:
            tags.append(play_kind)
        theab_kind = item.get("theabKindCd", "")
        if theab_kind and theab_kind not in tags:
            tags.append(theab_kind)

        results.append(ScreenSchedule(
            screen_name=screen_name,
            movie_title=movie_title,
            start_time=start_time,
            format_tags=tags,
        ))

    return results


def _get_megabox_screen_names(theater_code: str) -> list[str]:
    """Extract unique screen names from Megabox schedule."""
    try:
        items = _megabox_raw_schedule(theater_code)
    except Exception:
        logger.exception("Megabox screen names fetch failed for %s", theater_code)
        return []

    seen: dict[str, int] = {}  # name → first occurrence index
    for i, item in enumerate(items):
        name = item.get("theabExpoNm", "").strip()
        if name and name not in seen:
            seen[name] = i

    return sorted(seen, key=seen.get)  # type: ignore[arg-type]


# ------------------------------------------------------------------
# Lotte Cinema
# ------------------------------------------------------------------


def _lotte_raw_schedule(theater_code: str) -> list[dict]:
    """Fetch raw PlaySeqs.Items from Lotte Cinema API."""
    import json as _json
    from urllib.parse import urlencode
    from urllib.request import urlopen

    base = "http://www.lottecinema.co.kr"
    url = f"{base}/LCWS/Ticketing/TicketingData.aspx"

    today = datetime.now().strftime("%Y-%m-%d")
    param_list = {
        "channelType": "MW",
        "osType": "",
        "osVersion": "",
        "MethodName": "GetPlaySequence",
        "playDate": today,
        "cinemaID": theater_code,
        "representationMovieCode": "",
    }
    data = {"ParamList": _json.dumps(param_list)}
    payload = urlencode(data).encode("utf8")

    with urlopen(url, data=payload, timeout=15) as fin:
        content = fin.read().decode("utf8")
        resp = _json.loads(content)

    return resp.get("PlaySeqs", {}).get("Items", [])


def _fetch_lotte_screens(theater_code: str) -> list[ScreenSchedule]:
    """Parse Lotte Cinema API response into ScreenSchedule entries."""
    try:
        items = _lotte_raw_schedule(theater_code)
    except Exception:
        logger.exception("Lotte schedule fetch failed for %s", theater_code)
        return []

    results: list[ScreenSchedule] = []
    for item in items:
        # Use BrandNm_KR for richest screen description
        screen_name = (
            item.get("BrandNm_KR", "")
            or item.get("ScreenNameKR", "")
        ).strip()
        movie_title = item.get("MovieNameKR", "").strip()
        start_time = item.get("StartTime", "").strip()

        if not screen_name or not movie_title:
            continue

        tags: list[str] = []
        film = item.get("FilmNameKR", "")
        if film:
            tags.append(film)
        sound = item.get("SoundTypeNameKR", "")
        if sound and sound != "일반사운드":
            tags.append(sound)
        screen_div = item.get("ScreenDivisionNameKR", "")
        if screen_div and screen_div != "일반":
            tags.append(screen_div)

        results.append(ScreenSchedule(
            screen_name=screen_name,
            movie_title=movie_title,
            start_time=start_time,
            format_tags=tags,
        ))

    return results


def _get_lotte_screen_names(theater_code: str) -> list[str]:
    """Extract unique screen names from Lotte schedule."""
    try:
        items = _lotte_raw_schedule(theater_code)
    except Exception:
        logger.exception("Lotte screen names fetch failed for %s", theater_code)
        return []

    seen: dict[str, int] = {}
    for i, item in enumerate(items):
        name = (
            item.get("BrandNm_KR", "")
            or item.get("ScreenNameKR", "")
        ).strip()
        if name and name not in seen:
            seen[name] = i

    return sorted(seen, key=seen.get)  # type: ignore[arg-type]


# ------------------------------------------------------------------
# CGV (self-healing via Playwright)
# ------------------------------------------------------------------


async def _fetch_cgv_screens(theater_code: str) -> list[ScreenSchedule]:
    """Fetch CGV screens using self-healing engine.

    CGV has no REST API — requires headless browser rendering.
    Uses the HealingEngine to extract screen-level schedule data.
    """
    from cinepyle.scrapers.cgv import _get_engine, _get_settings
    from cinepyle.healing.strategy import ExtractionTask
    from cinepyle.scrapers.browser import get_page

    # Look up region code for this theater
    mgr = _get_settings()
    region_code = "01"  # default Seoul
    if mgr:
        # Check cached theater list for region
        for t in mgr.get_cached_theater_list():
            if t.get("chain_key") == "cgv" and t.get("theater_code") == theater_code:
                region_code = t.get("region_code", "01") or "01"
                break

    theater_url = f"https://cgv.co.kr/cnm/bzplcCgv/{region_code}{theater_code}"

    task = ExtractionTask(
        task_id="cgv_screen_schedule",
        url=theater_url,
        description=(
            "Extract the full schedule from this CGV theater page. "
            "For each screening, return the screen/hall name (관 이름, e.g. 'IMAX', "
            "'4DX', '돌비시네마', '3관'), the movie title in Korean, and the showtime. "
            "Return a JSON array of objects: "
            '[{"screen": "IMAX", "movie": "인터스텔라", "time": "14:00"}, ...]. '
            "Include ALL screens and ALL movies, not just special formats."
        ),
        expected_type="list",
        validation_hint=(
            "Array of objects with 'screen', 'movie', 'time' keys. "
            "Screen names are Korean hall identifiers. "
            "Movie titles are in Korean."
        ),
        example_result=[
            {"screen": "IMAX", "movie": "인터스텔라", "time": "14:00"},
            {"screen": "3관", "movie": "듄: 파트2", "time": "16:30"},
        ],
    )

    hardcoded_js = """(() => {
    const results = [];
    const allText = document.body.innerText;
    const lines = allText.split('\\n').map(l => l.trim()).filter(l => l);
    let currentScreen = '';
    let currentMovie = '';
    for (const line of lines) {
        // Screen names often end with 관 or are format names
        if (line.match(/^\\d+관$|^IMAX|^4DX|^돌비|^ScreenX|^SCREENX|^씨네드셰프/i)
            || line.match(/관$/) && line.length < 20) {
            currentScreen = line;
            continue;
        }
        // Time pattern
        const timeMatch = line.match(/^(\\d{1,2}:\\d{2})/);
        if (timeMatch && currentMovie) {
            results.push({screen: currentScreen || 'unknown', movie: currentMovie, time: timeMatch[1]});
            continue;
        }
        // Movie title (non-time, non-empty, reasonable length)
        if (line.length > 1 && line.length < 50 && !line.match(/^[0-9:]+$/)
            && !line.match(/^\\d+석$/) && !line.match(/^잔여석/)) {
            currentMovie = line;
        }
    }
    return results.length > 0 ? results : null;
})()"""

    page = await get_page()
    try:
        await page.goto(theater_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        engine = _get_engine()
        raw = await engine.extract(page, task, hardcoded_js=hardcoded_js)

        if not raw or not isinstance(raw, list):
            return []

        results: list[ScreenSchedule] = []
        for entry in raw:
            if isinstance(entry, dict):
                results.append(ScreenSchedule(
                    screen_name=entry.get("screen", "").strip(),
                    movie_title=entry.get("movie", "").strip(),
                    start_time=entry.get("time", "").strip(),
                ))
        return results

    except Exception:
        logger.exception("CGV screen fetch failed for %s", theater_code)
        return []
    finally:
        await page.close()


# ------------------------------------------------------------------
# CineQ
# ------------------------------------------------------------------


def _fetch_cineq_screens(theater_code: str) -> list[ScreenSchedule]:
    """Fetch CineQ schedule — returns basic entries (no hall info in current API)."""
    try:
        from cinepyle.theaters.cineq import get_movie_schedule

        schedule = get_movie_schedule(theater_code)
        results: list[ScreenSchedule] = []
        for _code, info in schedule.items():
            title = info.get("Name", "").strip()
            for s in info.get("Schedules", []):
                results.append(ScreenSchedule(
                    screen_name="전체",
                    movie_title=title,
                    start_time=s.get("StartTime", ""),
                ))
        return results
    except Exception:
        logger.exception("CineQ schedule fetch failed for %s", theater_code)
        return []


def _get_cineq_screen_names(theater_code: str) -> list[str]:
    """CineQ doesn't expose individual screen names."""
    return []
