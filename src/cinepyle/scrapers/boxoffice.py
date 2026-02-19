"""Korean Film Council (KOBIS) daily box office API client."""

import json
import logging
from datetime import datetime, timedelta
from urllib.request import urlopen

logger = logging.getLogger(__name__)

KOBIS_BASE_URL = (
    "http://www.kobis.or.kr/kobisopenapi/webservice/rest/"
    "boxoffice/searchDailyBoxOfficeList.json"
)


def fetch_daily_box_office(api_key: str) -> list[dict]:
    """Fetch yesterday's daily box office and return simplified list.

    Returns a list of dicts with keys: rank, name, code.
    """
    target_dt = datetime.now() - timedelta(days=1)
    target_dt_str = target_dt.strftime("%Y%m%d")
    query_url = f"{KOBIS_BASE_URL}?key={api_key}&targetDt={target_dt_str}"

    with urlopen(query_url) as response:
        raw = json.loads(response.read().decode("utf-8"))

    return [
        {
            "rank": entry.get("rank"),
            "name": entry.get("movieNm"),
            "code": entry.get("movieCd"),
        }
        for entry in raw["boxOfficeResult"]["dailyBoxOfficeList"]
    ]


async def fetch_box_office_with_fallback(api_key: str) -> list[dict]:
    """Fetch box office rankings with Watcha Pedia fallback.

    If api_key is provided, tries KOFIC API first.
    If api_key is empty or KOFIC call fails, falls back to
    Playwright-based Watcha Pedia scraping.

    Returns a list of dicts with keys: rank, name, code.
    """
    if api_key:
        try:
            return fetch_daily_box_office(api_key)
        except Exception:
            logger.exception("KOFIC box office failed, trying Watcha fallback")

    try:
        from cinepyle.browser.watcha_boxoffice import fetch_watcha_box_office

        return await fetch_watcha_box_office()
    except ImportError:
        logger.error("Playwright not available for Watcha box office fallback")
        return []
    except Exception:
        logger.exception("Watcha box office fallback also failed")
        return []
