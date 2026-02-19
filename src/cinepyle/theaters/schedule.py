"""Unified schedule fetching with screen info and date support.

Provides a common data model and per-chain fetchers for Lotte, MegaBox,
and CGV schedules.  Existing per-chain get_movie_schedule() functions
in lotte.py / megabox.py / cgv.py are NOT modified.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

import requests

from cinepyle.theaters.models import (
    LOTTE_SCREEN_TYPE_MAP,
    MEGABOX_SCREEN_TYPE_MAP,
    SCREEN_TYPE_NORMAL,
)

logger = logging.getLogger(__name__)


@dataclass
class Screening:
    """A single showtime for a movie at a specific hall."""

    movie_name: str
    start_time: str  # "HH:MM" or "" if unavailable (CGV)
    remaining_seats: int
    screen_name: str  # e.g. "1관", "IMAX관"
    screen_type: str  # "imax", "4dx", "normal", etc.
    screen_id: str


@dataclass
class TheaterSchedule:
    """All screenings for one theater on one date."""

    chain: str
    theater_code: str
    theater_name: str
    date: str  # "YYYY-MM-DD"
    screenings: list[Screening] = field(default_factory=list)
    error: str = ""  # non-empty if fetch failed or partial data


# ---------------------------------------------------------------------------
# Lotte Cinema
# ---------------------------------------------------------------------------


def fetch_lotte_schedule(
    theater_code: str,
    theater_name: str = "",
    target_date: date | None = None,
) -> TheaterSchedule:
    """Fetch Lotte Cinema schedule with screen info."""
    from cinepyle.theaters.sync import LOTTE_TICKETING_URL, _lotte_api

    dt = target_date or date.today()
    date_str = dt.strftime("%Y-%m-%d")

    result = TheaterSchedule(
        chain="lotte",
        theater_code=theater_code,
        theater_name=theater_name,
        date=date_str,
    )

    # Try common composite ID patterns
    composite_ids = [f"1|1|{theater_code}", f"1|2|{theater_code}"]

    for composite_id in composite_ids:
        try:
            sched = _lotte_api(
                LOTTE_TICKETING_URL,
                MethodName="GetPlaySequence",
                playDate=date_str,
                cinemaID=composite_id,
                representationMovieCode="",
            )

            # Movie code → name mapping
            movie_names: dict[str, str] = {}
            for entry in sched.get("PlaySeqsHeader", {}).get("Items", []):
                movie_names[entry.get("MovieCode", "")] = entry.get(
                    "MovieNameKR", ""
                )

            for entry in sched.get("PlaySeqs", {}).get("Items", []):
                movie_code = entry.get("MovieCode", "")
                movie_name = movie_names.get(movie_code, "")
                if not movie_name:
                    continue

                screen_name = entry.get("ScreenNameKR", "")
                screen_div = str(entry.get("ScreenDivisionCode", "100"))
                screen_id = str(entry.get("ScreenID", ""))
                screen_type = LOTTE_SCREEN_TYPE_MAP.get(
                    screen_div, SCREEN_TYPE_NORMAL
                )

                start_time_raw = str(entry.get("StartTime", ""))
                # Normalize to HH:MM
                start_time = _normalize_time(start_time_raw)

                total_seats = int(entry.get("TotalSeatCount", 0) or 0)
                booked = int(entry.get("BookingSeatCount", 0) or 0)
                remaining = total_seats - booked

                result.screenings.append(
                    Screening(
                        movie_name=movie_name,
                        start_time=start_time,
                        remaining_seats=remaining,
                        screen_name=screen_name,
                        screen_type=screen_type,
                        screen_id=screen_id,
                    )
                )

            if result.screenings:
                break  # found data with this composite ID
        except Exception:
            logger.debug(
                "Lotte schedule failed for %s (%s)", theater_code, composite_id
            )

    if not result.screenings:
        result.error = "상영 정보를 가져올 수 없습니다"

    return result


# ---------------------------------------------------------------------------
# MegaBox
# ---------------------------------------------------------------------------

MEGABOX_SCHEDULE_URL = "https://www.megabox.co.kr/on/oh/ohc/Brch/schedulePage.do"


def fetch_megabox_schedule(
    theater_code: str,
    theater_name: str = "",
    target_date: date | None = None,
) -> TheaterSchedule:
    """Fetch MegaBox schedule with screen info."""
    dt = target_date or date.today()
    date_str = dt.strftime("%Y-%m-%d")
    play_de = dt.strftime("%Y%m%d")

    result = TheaterSchedule(
        chain="megabox",
        theater_code=theater_code,
        theater_name=theater_name,
        date=date_str,
    )

    try:
        resp = requests.post(
            MEGABOX_SCHEDULE_URL,
            data={
                "masterType": "brch",
                "brchNo": theater_code,
                "brchNo1": theater_code,
                "firstAt": "Y",
                "playDe": play_de,
            },
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.megabox.co.kr/",
            },
            timeout=10,
        )
        data = resp.json()

        for entry in data.get("megaMap", {}).get("movieFormList", []):
            movie_name = entry.get("movieNm", "")
            if not movie_name:
                continue

            screen_name = entry.get("theabExpoNm", "")
            screen_id = str(entry.get("theabNo", ""))
            kind_cd = entry.get("theabKindCd", "NOR")
            screen_type = MEGABOX_SCREEN_TYPE_MAP.get(
                kind_cd, SCREEN_TYPE_NORMAL
            )

            start_time = _normalize_time(entry.get("playStartTime", ""))
            remaining = int(entry.get("restSeatCnt", 0) or 0)

            result.screenings.append(
                Screening(
                    movie_name=movie_name,
                    start_time=start_time,
                    remaining_seats=remaining,
                    screen_name=screen_name,
                    screen_type=screen_type,
                    screen_id=screen_id,
                )
            )
    except Exception:
        logger.debug("MegaBox schedule failed for %s", theater_code)
        result.error = "상영 정보를 가져올 수 없습니다"

    return result


# ---------------------------------------------------------------------------
# CGV (movies per screen only — NO start times)
# ---------------------------------------------------------------------------


def fetch_cgv_schedule(
    theater_code: str,
    theater_name: str = "",
    target_date: date | None = None,
) -> TheaterSchedule:
    """Fetch CGV schedule with start times.

    Uses rtctlScopCd=08 to get full showtime data including start/end
    times and remaining seats.
    """
    from cinepyle.theaters.models import CGV_GRADE_NAME_MAP
    from cinepyle.theaters.sync import _cgv_get

    dt = target_date or date.today()
    date_str = dt.strftime("%Y-%m-%d")
    scn_ymd = dt.strftime("%Y%m%d")

    result = TheaterSchedule(
        chain="cgv",
        theater_code=theater_code,
        theater_name=theater_name,
        date=date_str,
    )

    try:
        data = _cgv_get(
            "/cnm/atkt/searchMovScnInfo",
            f"coCd=A420&siteNo={theater_code}&scnYmd={scn_ymd}&rtctlScopCd=08",
        )
        if not data:
            result.error = "상영 정보를 가져올 수 없습니다"
            return result

        raw = data.get("data", data)
        items = (
            raw
            if isinstance(raw, list)
            else raw.get("list", raw.get("movieScnList", []))
        )

        for item in items:
            movie_name = item.get("movNm", "") or item.get("expoProdNm", "")
            scns_no = str(item.get("scnsNo", ""))
            screen_name = item.get("expoScnsNm", "") or item.get("scnsNm", "")
            grade_name = item.get("tcscnsGradNm", "")

            if not movie_name or not scns_no:
                continue

            # Classify screen type
            screen_type = SCREEN_TYPE_NORMAL
            for keyword, stype in CGV_GRADE_NAME_MAP.items():
                if keyword in grade_name.upper() or keyword in screen_name.upper():
                    screen_type = stype
                    break

            # Start time (scnsrtTm: "0805" → "08:05")
            start_time = _normalize_time(item.get("scnsrtTm", ""))

            # Remaining seats: prefer frSeatCnt (free), fallback to stcnt (total)
            remaining = int(item.get("frSeatCnt", 0) or 0)
            if not remaining:
                remaining = int(item.get("stcnt", 0) or 0)

            result.screenings.append(
                Screening(
                    movie_name=movie_name,
                    start_time=start_time,
                    remaining_seats=remaining,
                    screen_name=screen_name,
                    screen_type=screen_type,
                    screen_id=scns_no,
                )
            )
    except Exception:
        logger.debug("CGV schedule failed for %s", theater_code)
        result.error = "상영 정보를 가져올 수 없습니다"

    return result


# ---------------------------------------------------------------------------
# Multi-theater dispatcher
# ---------------------------------------------------------------------------

_CHAIN_FETCHERS = {
    "cgv": fetch_cgv_schedule,
    "lotte": fetch_lotte_schedule,
    "megabox": fetch_megabox_schedule,
}


def fetch_schedules_for_theaters(
    theaters: list[tuple[str, str, str]],  # [(chain, theater_code, name), ...]
    target_date: date | None = None,
) -> list[TheaterSchedule]:
    """Fetch schedules for multiple theaters across chains (parallel)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch_one(args):
        chain, theater_code, name = args
        fetcher = _CHAIN_FETCHERS.get(chain)
        if not fetcher:
            return None
        try:
            return fetcher(theater_code, name, target_date)
        except Exception:
            logger.debug("Schedule fetch failed for %s:%s", chain, theater_code)
            return None

    results = []
    max_workers = min(len(theaters), 10)
    if max_workers == 0:
        return results

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, t): t for t in theaters}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result)

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_time(raw: str) -> str:
    """Normalize time string to HH:MM format.

    Handles: "1900", "19:00", "7:00 PM", empty string.
    """
    if not raw:
        return ""
    raw = raw.strip()

    # Already HH:MM
    if len(raw) == 5 and raw[2] == ":":
        return raw

    # HHMM format
    digits = raw.replace(":", "")
    if digits.isdigit() and len(digits) >= 3:
        digits = digits.zfill(4)
        return f"{digits[:2]}:{digits[2:4]}"

    return raw
