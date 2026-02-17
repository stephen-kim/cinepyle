"""CGV theater data access and schedule fetching.

Note: CGV migrated to a Next.js-based site in July 2025.
The old iframeTheater.aspx endpoint no longer works.
Schedule fetching uses the new CGV system URLs.
"""

import logging
import math
from datetime import datetime

import requests

from cinepyle.theaters.data_cgv import data

logger = logging.getLogger(__name__)

CGV_SCHEDULE_API = "https://cgv.co.kr/api/schedules"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://cgv.co.kr/",
}


def get_theater_list() -> list[dict]:
    """Return the static list of CGV theaters."""
    return data


def filter_nearest(
    theater_list: list[dict],
    latitude: float,
    longitude: float,
    n: int = 3,
) -> list[dict]:
    """Return the N nearest theaters from the list."""
    with_distance = []
    for theater in theater_list:
        dx = latitude - float(theater["Latitude"])
        dy = longitude - float(theater["Longitude"])
        dist = math.sqrt(dx**2 + dy**2)
        with_distance.append((dist, theater))

    with_distance.sort(key=lambda x: x[0])
    return [theater for _, theater in with_distance[:n]]


def get_movie_schedule(area_code: str, theater_code: str) -> str:
    """Fetch today's movie schedule for a CGV theater.

    Uses the new CGV API (post-July 2025 migration).
    Returns a formatted string with movie titles and showtimes.
    """
    today = datetime.now().strftime("%Y%m%d")

    try:
        resp = requests.get(
            CGV_SCHEDULE_API,
            params={"theaterCode": theater_code, "date": today},
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("CGV schedule API returned %s", resp.status_code)
            return (
                "CGV 상영시간표를 가져올 수 없습니다.\n"
                f"직접 확인: https://cgv.co.kr/cnm/bzplcCgv/{area_code}{theater_code}"
            )

        data = resp.json()
        lines = []

        for movie in data.get("movies", data.get("schedules", [])):
            title = movie.get("movieName", movie.get("title", ""))
            lines.append("============================")
            lines.append(f"* {title}")
            lines.append(" 상영시간   빈좌석")

            halls = movie.get("halls", movie.get("screenings", []))
            for hall in halls:
                times = hall.get("times", hall.get("showtimes", []))
                for t in times:
                    start = t.get("startTime", t.get("time", ""))
                    seats = t.get("remainSeats", t.get("seats", ""))
                    lines.append(f"  {start}      {seats}")

        return "\n".join(lines) if lines else "상영 중인 영화가 없습니다."

    except Exception:
        logger.exception("Failed to fetch CGV schedule")
        return (
            "CGV 상영시간표를 가져올 수 없습니다.\n"
            f"직접 확인: https://cgv.co.kr/cnm/bzplcCgv/{area_code}{theater_code}"
        )
