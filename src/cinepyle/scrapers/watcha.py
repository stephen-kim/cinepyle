"""Watcha Pedia average rating scraper.

Fetches average user ratings (평균 별점) from Watcha Pedia's public API.
No login required — uses the search endpoint to find a movie code,
then fetches the detail API for the average rating.
"""

import logging

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


class WatchaClient:
    """Watcha Pedia client for rating lookups (no login required)."""

    def __init__(self, email: str = "", password: str = "") -> None:
        # email/password kept for backward compat but no longer used
        self.session = requests.Session()
        self.session.headers.update(WATCHA_HEADERS)

    def login(self) -> bool:
        """No-op for backward compatibility. Always returns True."""
        return True

    def get_expected_rating(self, movie_name: str) -> float | None:
        """Search for a movie and return its average rating (평균 별점).

        Returns the average rating on a 5-point scale (e.g. 4.3),
        or None if the movie is not found or the rating is unavailable.
        """
        try:
            code = self._search_movie_code(movie_name)
            if not code:
                return None
            return self._fetch_rating(code)
        except Exception:
            logger.exception("Failed to get Watcha rating for %s", movie_name)
            return None

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

    def _fetch_rating(self, content_code: str) -> float | None:
        """Fetch the average rating from the content detail API.

        The API returns ratings_avg on a 10-point scale;
        we convert to 5-point scale for display.
        """
        try:
            resp = self.session.get(
                f"{WATCHA_API_URL}/api/contents/{content_code}",
                timeout=10,
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            content = data.get("result", {})
            ratings_avg = content.get("ratings_avg")
            if ratings_avg is not None:
                # Convert 10-point → 5-point scale
                return round(float(ratings_avg) / 2, 1)

            return None
        except Exception:
            logger.exception("Failed to fetch Watcha rating for %s", content_code)
            return None
