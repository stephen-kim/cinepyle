"""CGV IMAX screening scraper using Playwright with self-healing.

CGV migrated to a Next.js-based site in July 2025. This module uses
a headless browser to render the schedule page and extract IMAX
screening information. If the hardcoded extraction strategy breaks
(e.g. site redesign), the healing engine calls Claude to generate
a new strategy automatically.
"""

import logging

from cinepyle.config import ANTHROPIC_API_KEY, HEALING_DB_PATH
from cinepyle.healing.engine import HealingEngine
from cinepyle.healing.strategy import ExtractionTask
from cinepyle.scrapers.browser import get_page

logger = logging.getLogger(__name__)

# CGV용산아이파크몰
YONGSAN_THEATER_CODE = "0013"
YONGSAN_REGION_CODE = "01"

# New CGV URLs (post-July 2025)
CGV_THEATER_URL = (
    f"https://cgv.co.kr/cnm/bzplcCgv/{YONGSAN_REGION_CODE}{YONGSAN_THEATER_CODE}"
)
CGV_BOOKING_URL = "https://cgv.co.kr/cnm/movieBook/cinema"

# --- Healing setup ---

_engine: HealingEngine | None = None


def _get_engine() -> HealingEngine:
    global _engine
    if _engine is None:
        _engine = HealingEngine(ANTHROPIC_API_KEY, HEALING_DB_PATH)
    return _engine


IMAX_TASK = ExtractionTask(
    task_id="cgv_imax_title",
    url=CGV_THEATER_URL,
    description=(
        "This is a CGV movie theater schedule page for the Yongsan I'Park Mall "
        "location (CGV용산아이파크몰). Find any movie that is currently screening "
        "in an IMAX hall/screen. IMAX screenings are identified by the word 'IMAX' "
        "appearing in the screen name, hall name, or format label. Return the movie "
        "title (Korean name) of the movie showing in IMAX. If there is no IMAX "
        "screening listed on this page, return null."
    ),
    expected_type="string",
    validation_hint=(
        "Should be a Korean movie title, 1-50 characters, no HTML tags. "
        "Examples: '인터스텔라', '듄: 파트2', '오펜하이머'"
    ),
    example_result="인터스텔라",
)

HARDCODED_IMAX_JS = """(() => {
    // Strategy 1: Find IMAX in class names, traverse up for title
    const imaxEls = document.querySelectorAll("[class*='imax'], [class*='IMAX']");
    for (const el of imaxEls) {
        let parent = el;
        for (let i = 0; i < 10; i++) {
            parent = parent.parentElement;
            if (!parent) break;
            const title = parent.querySelector(
                '[class*="movie"], [class*="title"], h3, h4, strong'
            );
            if (title && title.textContent.trim().length > 0) {
                return title.textContent.trim();
            }
        }
    }
    // Strategy 2: Text search for IMAX mention
    const allText = document.body.innerText;
    const lines = allText.split('\\n').map(l => l.trim()).filter(l => l);
    for (let i = 0; i < lines.length; i++) {
        if (lines[i].toUpperCase().includes('IMAX')) {
            for (let j = i - 1; j >= Math.max(0, i - 5); j--) {
                if (lines[j].length > 1 && !lines[j].match(/^[0-9:]+$/)) {
                    return lines[j];
                }
            }
            return lines[i].replace(/IMAX/gi, '').trim() || lines[i];
        }
    }
    return null;
})()"""


async def check_imax_screening() -> tuple[str, str] | None:
    """Check CGV용산아이파크몰 for IMAX screenings.

    Uses the self-healing engine: tries cached strategy, then
    hardcoded JS, then asks Claude to generate a new strategy.

    Returns (movie_title, booking_url) if an IMAX screening is found,
    or None if no IMAX screening is currently listed.
    """
    page = await get_page()
    try:
        await page.goto(CGV_THEATER_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Quick check: is "IMAX" even on the page?
        content = await page.content()
        if "IMAX" not in content.upper():
            return None

        # Use healing engine
        engine = _get_engine()
        title = await engine.extract(page, IMAX_TASK, hardcoded_js=HARDCODED_IMAX_JS)

        if title:
            booking_url = f"{CGV_BOOKING_URL}?theaterCode={YONGSAN_THEATER_CODE}"
            return title, booking_url

        return None

    except Exception:
        logger.exception("Failed to check IMAX screening")
        return None
    finally:
        await page.close()
