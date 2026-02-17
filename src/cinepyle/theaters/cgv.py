"""CGV theater data access and schedule fetching with self-healing.

Note: CGV migrated to a Next.js-based site in July 2025.
The old iframeTheater.aspx endpoint no longer works.
Schedule fetching uses Playwright to render the CSR page,
with self-healing extraction via Claude API.
"""

import logging
import math

from cinepyle.config import (
    ANTHROPIC_API_KEY,
    GEMINI_API_KEY,
    HEALING_DB_PATH,
    OPENAI_API_KEY,
)
from cinepyle.healing.engine import HealingEngine
from cinepyle.healing.llm import resolve_llm_config
from cinepyle.healing.strategy import ExtractionTask
from cinepyle.scrapers.browser import get_page
from cinepyle.theaters.data_cgv import data

logger = logging.getLogger(__name__)

CGV_THEATER_BASE_URL = "https://cgv.co.kr/cnm/bzplcCgv"

# --- Healing setup ---

_engine: HealingEngine | None = None


def _get_engine() -> HealingEngine:
    global _engine
    if _engine is None:
        _engine = HealingEngine(
            resolve_llm_config(ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY),
            HEALING_DB_PATH,
        )
    return _engine


CGV_SCHEDULE_TASK = ExtractionTask(
    task_id="cgv_movie_schedule",
    url=f"{CGV_THEATER_BASE_URL}/...",
    description=(
        "This is a CGV movie theater schedule page. Extract the list of movies "
        "and their showtimes. Return an array of objects, each with a 'title' "
        "(movie name in Korean) and 'times' (array of showtime strings like "
        "'10:30', '13:00'). Group showtimes under their movie title."
    ),
    expected_type="list[dict]",
    validation_hint=(
        "Should be an array of {title: string, times: string[]}. "
        "Each title is a Korean movie name. Each time is HH:MM format."
    ),
    example_result='[{"title": "인터스텔라", "times": ["10:30", "14:00"]}]',
)

HARDCODED_SCHEDULE_JS = """(() => {
    const allText = document.body.innerText;
    const lines = allText.split('\\n').map(l => l.trim()).filter(l => l);

    let currentMovie = null;
    const timePattern = /^\\d{1,2}:\\d{2}/;
    const result = [];

    for (const line of lines) {
        if (line.length < 2) continue;
        if (timePattern.test(line) && currentMovie) {
            currentMovie.times.push(line);
        } else if (line.length > 2 && !timePattern.test(line)
                   && !line.match(/^[0-9]+$/)
                   && !line.match(/^(관|석|층|원|명)$/)
                   && line.length < 50) {
            if (currentMovie && currentMovie.times.length > 0) {
                result.push(currentMovie);
            }
            currentMovie = { title: line, times: [] };
        }
    }
    if (currentMovie && currentMovie.times.length > 0) {
        result.push(currentMovie);
    }
    return result.length > 0 ? result : null;
})()"""


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
    the self-healing engine to extract schedule data. If the hardcoded
    extraction breaks, Claude generates a new strategy automatically.
    """
    theater_url = f"{CGV_THEATER_BASE_URL}/{area_code}{theater_code}"

    page = await get_page()
    try:
        await page.goto(theater_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Use healing engine for schedule extraction
        engine = _get_engine()
        schedule = await engine.extract(
            page, CGV_SCHEDULE_TASK, hardcoded_js=HARDCODED_SCHEDULE_JS
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
