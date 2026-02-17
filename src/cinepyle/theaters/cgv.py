"""CGV theater data access and schedule fetching.

Note: CGV migrated to a Next.js-based site in July 2025.
The old iframeTheater.aspx endpoint no longer works.
Schedule fetching uses Playwright to render the CSR page.
"""

import logging
import math

from cinepyle.scrapers.browser import get_page
from cinepyle.theaters.data_cgv import data

logger = logging.getLogger(__name__)

CGV_THEATER_BASE_URL = "https://cgv.co.kr/cnm/bzplcCgv"


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


async def get_movie_schedule(area_code: str, theater_code: str) -> str:
    """Fetch today's movie schedule for a CGV theater.

    Uses Playwright to render the Next.js-based theater page and
    extract schedule information from the fully rendered DOM.
    Returns a formatted string with movie titles and showtimes.
    """
    theater_url = f"{CGV_THEATER_BASE_URL}/{area_code}{theater_code}"

    page = await get_page()
    try:
        await page.goto(theater_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Extract schedule from the rendered page
        schedule = await page.evaluate(
            """() => {
                const movies = [];
                // Try common schedule container selectors
                const containers = document.querySelectorAll(
                    '[class*="movie"], [class*="schedule"], [class*="timetable"], article, section'
                );

                // Strategy 1: Look for structured movie/time data
                const allText = document.body.innerText;
                const lines = allText.split('\\n').map(l => l.trim()).filter(l => l);

                let currentMovie = null;
                const timePattern = /^\\d{1,2}:\\d{2}/;
                const result = [];

                for (const line of lines) {
                    // Skip very short lines or common UI text
                    if (line.length < 2) continue;

                    // If this line looks like a time, add it to current movie
                    if (timePattern.test(line) && currentMovie) {
                        currentMovie.times.push(line);
                    }
                    // If it's a substantial text that doesn't look like a time or number,
                    // treat it as a potential movie title
                    else if (line.length > 2 && !timePattern.test(line)
                             && !line.match(/^[0-9]+$/)
                             && !line.match(/^(관|석|층|원|명)$/)
                             && line.length < 50) {
                        // Check if the previous movie had times
                        if (currentMovie && currentMovie.times.length > 0) {
                            result.push(currentMovie);
                        }
                        currentMovie = { title: line, times: [] };
                    }
                }
                // Don't forget the last movie
                if (currentMovie && currentMovie.times.length > 0) {
                    result.push(currentMovie);
                }

                return result;
            }"""
        )

        if not schedule:
            return (
                "상영 중인 영화가 없거나 스케줄을 파싱할 수 없습니다.\n"
                f"직접 확인: {theater_url}"
            )

        lines = []
        for movie in schedule:
            lines.append("============================")
            lines.append(f"* {movie['title']}")
            for time_info in movie["times"]:
                lines.append(f"  {time_info}")

        return "\n".join(lines)

    except Exception:
        logger.exception("Failed to fetch CGV schedule via Playwright")
        return (
            "CGV 상영시간표를 가져올 수 없습니다.\n"
            f"직접 확인: {theater_url}"
        )
    finally:
        await page.close()
