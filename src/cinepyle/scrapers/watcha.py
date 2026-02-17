"""Watcha Pedia expected rating scraper using Playwright.

Watcha Pedia does not provide a public API for predicted ratings.
This module logs in via a headless browser and scrapes the expected
rating (예상 별점) for a given movie title.
"""

import logging

from cinepyle.scrapers.browser import get_page

logger = logging.getLogger(__name__)

WATCHA_BASE_URL = "https://pedia.watcha.com"
WATCHA_LOGIN_URL = f"{WATCHA_BASE_URL}/ko-KR/sign_in"
WATCHA_SEARCH_URL = f"{WATCHA_BASE_URL}/ko-KR/search"


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

            # Check if login succeeded by looking for user menu or absence of login form
            still_on_login = await page.query_selector(
                'input[type="password"]'
            )
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

            # Extract expected rating from detail page
            rating = await page.evaluate(
                """() => {
                    const allText = document.body.innerText;
                    // Look for patterns like "예상 ★ 3.5" or "예상별점 3.5"
                    const patterns = [
                        /예상[\\s]*[★☆]*[\\s]*([\\d.]+)/,
                        /predicted[\\s]*(?:rating)?[\\s]*:?[\\s]*([\\d.]+)/i,
                        /expected[\\s]*(?:rating)?[\\s]*:?[\\s]*([\\d.]+)/i,
                    ];
                    for (const pat of patterns) {
                        const match = allText.match(pat);
                        if (match) return parseFloat(match[1]);
                    }

                    // Also check for rating elements in the DOM
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
                }"""
            )

            if rating is not None:
                return round(float(rating), 1)

            return None

        except Exception:
            logger.exception("Failed to get Watcha rating for %s", movie_name)
            return None
        finally:
            await page.close()
