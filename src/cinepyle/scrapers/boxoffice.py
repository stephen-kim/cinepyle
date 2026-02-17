"""Korean Film Council (KOBIS) daily box office API client."""

import json
from datetime import datetime, timedelta
from urllib.request import urlopen

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
