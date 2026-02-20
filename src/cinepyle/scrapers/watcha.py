"""Watcha Pedia rating scraper.

Fetches movie ratings from Watcha Pedia:
- Average rating (평균 별점) — public, no login required
- Predicted rating (예상 별점) — personalized, requires login

Uses the search endpoint to find a movie code, then fetches the
detail API for ratings.
"""

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

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


@dataclass
class WatchaRating:
    """Watcha Pedia rating data for a movie."""

    average: float | None = None  # 평균 별점 (5-point scale)
    predicted: float | None = None  # 예상 별점 (5-point scale, personalized)

    @property
    def display(self) -> str:
        """Format for display: '⭐4.3 (예상 4.5)' or '⭐4.3'."""
        parts = []
        if self.average is not None:
            parts.append(f"⭐{self.average}")
        if self.predicted is not None:
            parts.append(f"예상 {self.predicted}")
        if not parts:
            return ""
        if self.average is not None and self.predicted is not None:
            return f"⭐{self.average} (예상 {self.predicted})"
        return parts[0]


class WatchaClient:
    """Watcha Pedia client for rating lookups.

    If email/password provided, logs in for personalized predicted ratings.
    Otherwise, returns average ratings only.
    """

    def __init__(self, email: str = "", password: str = "") -> None:
        self.email = email
        self.password = password
        self.session = requests.Session()
        self.session.headers.update(WATCHA_HEADERS)
        self._logged_in = False

    def login(self) -> bool:
        """Log in to Watcha Pedia for personalized ratings."""
        if not self.email or not self.password:
            return False
        try:
            resp = self.session.post(
                f"{WATCHA_API_URL}/api/sessions",
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

    def _ensure_login(self) -> None:
        """Attempt login if credentials available and not yet logged in."""
        if not self._logged_in and self.email and self.password:
            self.login()

    def get_rating(self, movie_name: str) -> WatchaRating:
        """Search for a movie and return its ratings.

        Returns a WatchaRating with average and (if logged in) predicted rating,
        both on a 5-point scale.
        """
        self._ensure_login()
        try:
            code = self._search_movie_code(movie_name)
            if not code:
                return WatchaRating()
            return self._fetch_rating(code)
        except Exception:
            logger.exception("Failed to get Watcha rating for %s", movie_name)
            return WatchaRating()

    def get_expected_rating(self, movie_name: str) -> float | None:
        """Backward-compatible method: returns best available rating.

        Returns predicted rating if logged in, otherwise average rating.
        """
        rating = self.get_rating(movie_name)
        return rating.predicted or rating.average

    def _search_movie_code(self, movie_name: str) -> str | None:
        """Search Watcha Pedia and return the content code for the best match."""
        try:
            resp = self.session.get(
                f"{WATCHA_API_URL}/api/searches",
                params={"query": movie_name},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning("Watcha search failed: %s", resp.status_code)
                return None

            data = resp.json()
            result = data.get("result", {})

            # Try top_results first (most relevant), then movies list
            for source in [result.get("top_results", []), result.get("movies", [])]:
                if not isinstance(source, list):
                    continue
                for item in source:
                    if item.get("content_type") == "movies":
                        return item.get("code")

            return None
        except Exception:
            logger.exception("Watcha search error for %s", movie_name)
            return None

    def _fetch_rating(self, content_code: str) -> WatchaRating:
        """Fetch ratings from the content detail API.

        The API returns ratings on a 10-point scale;
        we convert to 5-point scale for display.
        """
        try:
            resp = self.session.get(
                f"{WATCHA_API_URL}/api/contents/{content_code}",
                timeout=10,
            )
            if resp.status_code != 200:
                return WatchaRating()

            data = resp.json()
            content = data.get("result", {})

            # Average rating (public)
            avg_raw = content.get("ratings_avg")
            average = round(float(avg_raw) / 2, 1) if avg_raw else None

            # Predicted rating (personalized, requires login)
            predicted = None
            ctx = content.get("current_context", {})
            if ctx:
                pred_raw = ctx.get("predicted_rating")
                if pred_raw is not None:
                    predicted = round(float(pred_raw) / 2, 1)

            return WatchaRating(average=average, predicted=predicted)
        except Exception:
            logger.exception("Failed to fetch Watcha rating for %s", content_code)
            return WatchaRating()
