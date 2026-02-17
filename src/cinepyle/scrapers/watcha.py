"""Watcha Pedia expected rating scraper using Playwright with self-healing.

Watcha Pedia does not provide a public API for predicted ratings.
This module logs in via a headless browser, searches for movies,
and extracts the expected rating from the detail page.

The rating extraction step uses the self-healing engine so it can
adapt when Watcha changes their page structure.
"""

import logging

from cinepyle.config import ANTHROPIC_API_KEY, HEALING_DB_PATH
from cinepyle.healing.engine import HealingEngine
from cinepyle.healing.strategy import ExtractionTask
from cinepyle.scrapers.browser import get_page

logger = logging.getLogger(__name__)

WATCHA_BASE_URL = "https://pedia.watcha.com"
WATCHA_LOGIN_URL = f"{WATCHA_BASE_URL}/ko-KR/sign_in"
WATCHA_SEARCH_URL = f"{WATCHA_BASE_URL}/ko-KR/search"

# --- Healing setup ---

_engine: HealingEngine | None = None


def _get_engine() -> HealingEngine:
    global _engine
    if _engine is None:
        _engine = HealingEngine(ANTHROPIC_API_KEY, HEALING_DB_PATH)
    return _engine


WATCHA_RATING_TASK = ExtractionTask(
    task_id="watcha_expected_rating",
    url=f"{WATCHA_BASE_URL}/ko-KR/contents/...",
    description=(
        "This is a Watcha Pedia movie detail page. Find the predicted/expected "
        "rating (예상 별점) for the logged-in user. This is typically displayed "
        "near the top of the page as a star rating with a label like '예상' "
        "(expected) or '예상 별점'. Return the numeric rating value as a number. "
        "The rating scale is 0.5 to 5.0."
    ),
    expected_type="float",
    validation_hint="Should be a float between 0.5 and 5.0, representing a star rating.",
    example_result="3.5",
)

HARDCODED_RATING_JS = """(() => {
    // Strategy 1: Search for 예상 pattern in text
    const allText = document.body.innerText;
    const patterns = [
        /예상[\\s]*[★☆]*[\\s]*([\\d.]+)/,
        /predicted[\\s]*(?:rating)?[\\s]*:?[\\s]*([\\d.]+)/i,
        /expected[\\s]*(?:rating)?[\\s]*:?[\\s]*([\\d.]+)/i,
    ];
    for (const pat of patterns) {
        const match = allText.match(pat);
        if (match) return parseFloat(match[1]);
    }
    // Strategy 2: Check DOM elements with rating-related classes
    const ratingEls = document.querySelectorAll(
        '[class*="predicted"], [class*="expected"], [class*="rating"]'
    );
    for (const el of ratingEls) {
        const text = el.textContent || '';
        const numMatch = text.match(/(\\d+\\.?\\d*)/);
        if (numMatch) {
            const val = parseFloat(numMatch[1]);
            if (val > 0 && val <= 5) return val;
        }
    }
    return null;
})()"""


class WatchaClient:
    """Watcha Pedia client that handles login and rating lookups via Playwright."""

    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password
        self._logged_in = False

    async def login(self) -> bool:
        """Log in to Watcha Pedia using email/password via headless browser.

        Returns True on success, False on failure.
        """
        page = await get_page()
        try:
            await page.goto(WATCHA_LOGIN_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(1000)

            # Fill login form
            email_input = await page.query_selector(
                'input[type="email"], input[name="email"], input[placeholder*="이메일"]'
            )
            password_input = await page.query_selector(
                'input[type="password"], input[name="password"]'
            )

            if not email_input or not password_input:
                logger.warning("Watcha login form not found")
                return False

            await email_input.fill(self.email)
            await password_input.fill(self.password)

            # Click login button
            login_btn = await page.query_selector(
                'button[type="submit"], button:has-text("로그인")'
            )
            if login_btn:
                await login_btn.click()
            else:
                await page.keyboard.press("Enter")

            # Wait for navigation after login
            await page.wait_for_timeout(3000)

            # Check if login succeeded
            still_on_login = await page.query_selector('input[type="password"]')
            if still_on_login:
                logger.warning("Watcha Pedia login failed: still on login page")
                return False

            self._logged_in = True
            logger.info("Watcha Pedia login successful")
            return True

        except Exception:
            logger.exception("Watcha Pedia login error")
            return False
        finally:
            await page.close()

    async def _ensure_login(self) -> bool:
        """Ensure we have an active session."""
        if not self._logged_in:
            return await self.login()
        return True

    async def get_expected_rating(self, movie_name: str) -> float | None:
        """Search for a movie and return its expected rating (예상 별점).

        Uses self-healing extraction for the rating value so it can
        adapt when Watcha changes their page layout.

        Returns the predicted rating as a float (e.g. 3.5), or None
        if the movie is not found or the rating is unavailable.
        """
        if not await self._ensure_login():
            return None

        page = await get_page()
        try:
            # Navigate to search page
            search_url = f"{WATCHA_SEARCH_URL}?query={movie_name}"
            await page.goto(search_url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # Click first movie result
            first_result = await page.query_selector(
                'a[href*="/contents/"], [class*="search"] a[href*="/contents/"]'
            )
            if not first_result:
                logger.info("No Watcha search result for: %s", movie_name)
                return None

            await first_result.click()
            await page.wait_for_timeout(2000)

            # Extract rating using healing engine
            engine = _get_engine()
            rating = await engine.extract(
                page, WATCHA_RATING_TASK, hardcoded_js=HARDCODED_RATING_JS
            )

            if rating is not None:
                return round(float(rating), 1)

            return None

        except Exception:
            logger.exception("Failed to get Watcha rating for %s", movie_name)
            return None
        finally:
            await page.close()
