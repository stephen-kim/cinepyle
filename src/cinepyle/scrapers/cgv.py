"""CGV IMAX screening scraper using Playwright with self-healing.

CGV migrated to a Next.js-based site in July 2025. This module uses
a headless browser to render the schedule page and extract IMAX
screening information. If the hardcoded extraction strategy breaks
(e.g. site redesign), the healing engine calls Claude to generate
a new strategy automatically.
"""

import logging

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

logger = logging.getLogger(__name__)

# Default theater (CGV용산아이파크몰) — overridable via dashboard
DEFAULT_THEATER_CODE = "0013"
DEFAULT_REGION_CODE = "01"

CGV_BOOKING_URL = "https://cgv.co.kr/cnm/movieBook/cinema"

# --- Healing setup ---

_engine: HealingEngine | None = None


def _get_settings():
    """Get SettingsManager (returns None if not initialised)."""
    try:
        from cinepyle.dashboard.settings_manager import SettingsManager
        return SettingsManager.get_instance()
    except (RuntimeError, ImportError):
        return None


def _get_theater_config() -> tuple[str, str]:
    """Return (theater_code, region_code) from settings or defaults."""
    mgr = _get_settings()
    if mgr:
        code = mgr.get("preferred_theater_code", DEFAULT_THEATER_CODE)
        region = mgr.get("preferred_theater_region", DEFAULT_REGION_CODE)
        return code, region
    return DEFAULT_THEATER_CODE, DEFAULT_REGION_CODE


def _get_engine() -> HealingEngine:
    global _engine
    if _engine is None:
        mgr = _get_settings()
        if mgr:
            anthropic_key = mgr.get("credential:anthropic_api_key") or ANTHROPIC_API_KEY
            openai_key = mgr.get("credential:openai_api_key") or OPENAI_API_KEY
            gemini_key = mgr.get("credential:gemini_api_key") or GEMINI_API_KEY
            priority = mgr.get_llm_priority()
        else:
            anthropic_key, openai_key, gemini_key = ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY
            priority = None
        _engine = HealingEngine(
            resolve_llm_config(anthropic_key, openai_key, gemini_key, priority=priority),
            HEALING_DB_PATH,
        )
    return _engine


def _make_imax_task(theater_url: str) -> ExtractionTask:
    """Build an IMAX extraction task for the given theater URL."""
    return ExtractionTask(
        task_id="cgv_imax_title",
        url=theater_url,
        description=(
            "This is a CGV movie theater schedule page. Find any movie that is "
            "currently screening in an IMAX hall/screen. IMAX screenings are "
            "identified by the word 'IMAX' appearing in the screen name, hall "
            "name, or format label. Return the movie title (Korean name) of the "
            "movie showing in IMAX. If there is no IMAX screening listed on "
            "this page, return null."
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
    """Check preferred CGV theater for IMAX screenings.

    Theater is read from SettingsManager (defaults to CGV용산아이파크몰).
    Uses the self-healing engine: tries cached strategy, then
    hardcoded JS, then asks Claude to generate a new strategy.

    Returns (movie_title, booking_url) if an IMAX screening is found,
    or None if no IMAX screening is currently listed.
    """
    theater_code, region_code = _get_theater_config()
    theater_url = f"https://cgv.co.kr/cnm/bzplcCgv/{region_code}{theater_code}"

    page = await get_page()
    try:
        await page.goto(theater_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Quick check: is "IMAX" even on the page?
        content = await page.content()
        if "IMAX" not in content.upper():
            return None

        # Use healing engine
        engine = _get_engine()
        task = _make_imax_task(theater_url)
        title = await engine.extract(page, task, hardcoded_js=HARDCODED_IMAX_JS)

        if title:
            booking_url = f"{CGV_BOOKING_URL}?theaterCode={theater_code}"
            return title, booking_url

        return None

    except Exception:
        logger.exception("Failed to check IMAX screening")
        return None
    finally:
        await page.close()
