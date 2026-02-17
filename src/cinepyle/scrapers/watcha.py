"""Watcha Pedia expected rating scraper.

Watcha Pedia does not provide a public API for predicted ratings.
This module logs in via the web interface and scrapes the expected
rating (예상 별점) for a given movie title.
"""

import logging
import re

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

WATCHA_BASE_URL = "https://pedia.watcha.com"
WATCHA_API_URL = "https://api-pedia.watcha.com"

WATCHA_HEADERS = {
    "x-watcha-client": "watcha-WebApp",
    "x-watcha-client-language": "ko",
    "x-watcha-client-region": "KR",
    "x-watcha-client-version": "2.1.0",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}


class WatchaClient:
    """Watcha Pedia client that handles login and rating lookups."""

    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password
        self.session = requests.Session()
        self.session.headers.update(WATCHA_HEADERS)
        self._logged_in = False

    def login(self) -> bool:
        """Log in to Watcha Pedia using email/password.

        Returns True on success, False on failure.
        """
        try:
            resp = self.session.post(
                f"{WATCHA_API_URL}/api/auth",
                json={"email": self.email, "password": self.password},
                timeout=15,
            )
            if resp.status_code == 200:
                self._logged_in = True
                logger.info("Watcha Pedia login successful")
                return True

            logger.warning(
                "Watcha Pedia login failed: %s %s",
                resp.status_code,
                resp.text[:200],
            )
            return False
        except Exception:
            logger.exception("Watcha Pedia login error")
            return False

    def _ensure_login(self) -> bool:
        """Ensure we have an active session."""
        if not self._logged_in:
            return self.login()
        return True

    def get_expected_rating(self, movie_name: str) -> float | None:
        """Search for a movie and return its expected rating (예상 별점).

        Returns the predicted rating as a float (e.g. 3.5), or None
        if the movie is not found or the rating is unavailable.
        """
        if not self._ensure_login():
            return None

        try:
            search_resp = self.session.get(
                f"{WATCHA_API_URL}/api/searches",
                params={"query": movie_name},
                timeout=15,
            )
            if search_resp.status_code != 200:
                logger.warning("Watcha search failed: %s", search_resp.status_code)
                return None

            data = search_resp.json()
            results = data.get("result", {}).get("result", {}).get("body", [])
            if not results:
                return None

            # Find the first movie result
            for item in results:
                content = item.get("content", {})
                if content.get("content_type") == "movies":
                    # The predicted rating may be in the response
                    predicted = content.get("ratings_avg")
                    if predicted:
                        return round(float(predicted), 1)

                    # Try fetching the detail page for the predicted rating
                    code = content.get("code")
                    if code:
                        return self._fetch_detail_rating(code)

            return None
        except Exception:
            logger.exception("Failed to get Watcha rating for %s", movie_name)
            return None

    def _fetch_detail_rating(self, content_code: str) -> float | None:
        """Fetch the predicted rating from a movie's detail page."""
        try:
            resp = self.session.get(
                f"{WATCHA_BASE_URL}/ko-KR/contents/{content_code}",
                timeout=15,
            )
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "lxml")
            # Look for the predicted/expected rating element
            rating_el = soup.select_one("[class*='predicted'], [class*='expected']")
            if rating_el:
                match = re.search(r"(\d+\.?\d*)", rating_el.text)
                if match:
                    return round(float(match.group(1)), 1)

            return None
        except Exception:
            logger.exception("Failed to fetch detail rating for %s", content_code)
            return None
