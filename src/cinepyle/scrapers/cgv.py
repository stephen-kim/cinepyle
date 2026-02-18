"""CGV IMAX screening scraper.

CGV migrated to a Next.js-based site in July 2025. The old
iframeTheater.aspx endpoint no longer works. The new site uses
internal API endpoints under cgv.co.kr for schedule data.

This module attempts to fetch schedule data from the new CGV API.
If the API structure changes, the CSS selectors / JSON paths will
need to be updated accordingly.
"""

import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

# CGV new system API endpoint (discovered from Next.js site)
CGV_SCHEDULE_API = "https://cgv.co.kr/api/schedules"

# CGV용산아이파크몰 identifiers
YONGSAN_THEATER_CODE = "0013"
YONGSAN_REGION_CODE = "01"

# Booking deeplink (new system)
CGV_BOOKING_BASE = "https://cgv.co.kr/cnm/movieBook/cinema"

# Fallback: direct theater page
CGV_THEATER_PAGE = "https://cgv.co.kr/cnm/bzplcCgv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://cgv.co.kr/",
}


def check_imax_screening() -> tuple[str, str] | None:
    """Check CGV용산아이파크몰 for IMAX screenings.

    Attempts multiple strategies to find IMAX screenings:
    1. Try the new CGV API endpoint for schedule data
    2. Fall back to scraping the theater page

    Returns (movie_title, booking_url) if an IMAX screening is found,
    or None if no IMAX screening is currently listed.
    """
    today = datetime.now().strftime("%Y%m%d")

    # Strategy 1: Try new API endpoint
    result = _check_via_api(today)
    if result is not None:
        return result

    # Strategy 2: Try scraping the theater page directly
    result = _check_via_theater_page(today)
    if result is not None:
        return result

    return None


def _check_via_api(date: str) -> tuple[str, str] | None:
    """Try fetching IMAX schedule via CGV's internal API."""
    try:
        resp = requests.get(
            CGV_SCHEDULE_API,
            params={
                "theaterCode": YONGSAN_THEATER_CODE,
                "date": date,
            },
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            logger.debug("CGV API returned %s", resp.status_code)
            return None

        data = resp.json()

        # Look for IMAX screenings in the response
        # The exact JSON structure depends on CGV's API implementation
        for movie in data.get("movies", data.get("schedules", [])):
            halls = movie.get("halls", movie.get("screenings", []))
            for hall in halls:
                hall_name = str(
                    hall.get("hallName", hall.get("screenName", ""))
                )
                if "IMAX" in hall_name.upper():
                    title = movie.get(
                        "movieName", movie.get("title", "Unknown")
                    )
                    booking_url = (
                        f"{CGV_BOOKING_BASE}"
                        f"?theaterCode={YONGSAN_THEATER_CODE}"
                    )
                    return title, booking_url

        return None
    except Exception:
        logger.debug("CGV API request failed", exc_info=True)
        return None


def _check_via_theater_page(date: str) -> tuple[str, str] | None:
    """Try scraping the CGV theater page for IMAX info."""
    try:
        # Try the new theater page URL pattern
        url = f"{CGV_THEATER_PAGE}/{YONGSAN_REGION_CODE}{YONGSAN_THEATER_CODE}"
        resp = requests.get(url, headers=HEADERS, timeout=10)

        if resp.status_code != 200:
            logger.debug("CGV theater page returned %s", resp.status_code)
            return None

        # Check for IMAX in the page content
        content = resp.text.lower()
        if "imax" not in content:
            return None

        # Try to extract from Next.js __NEXT_DATA__
        import json
        import re

        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            resp.text,
        )
        if match:
            next_data = json.loads(match.group(1))
            props = next_data.get("props", {}).get("pageProps", {})

            # Look through the data for IMAX screenings
            for key, value in props.items():
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            item_str = json.dumps(item).upper()
                            if "IMAX" in item_str:
                                title = item.get(
                                    "movieName",
                                    item.get("title", "IMAX 영화"),
                                )
                                booking_url = (
                                    f"{CGV_BOOKING_BASE}"
                                    f"?theaterCode={YONGSAN_THEATER_CODE}"
                                )
                                return title, booking_url

        # Fallback: we know IMAX exists but can't extract the title
        booking_url = (
            f"{CGV_BOOKING_BASE}?theaterCode={YONGSAN_THEATER_CODE}"
        )
        return "IMAX 상영 (제목 확인 필요)", booking_url

    except Exception:
        logger.debug("CGV theater page scraping failed", exc_info=True)
        return None
