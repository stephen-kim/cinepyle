"""KOFIC movie list API client for detecting new and upcoming releases."""

import json
from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen

KOFIC_MOVIE_LIST_URL = (
    "http://www.kobis.or.kr/kobisopenapi/webservice/rest/"
    "movie/searchMovieList.json"
)


def fetch_recent_releases(api_key: str, days_back: int = 7) -> list[dict]:
    """Fetch movies released within the last N days.

    Returns a list of dicts with keys: code, name, open_date, genre.
    """
    today = datetime.now()
    start_date = (today - timedelta(days=days_back)).strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")

    params = {
        "key": api_key,
        "openStartDt": start_date[:4],
        "openEndDt": end_date[:4],
        "itemPerPage": "50",
    }
    query_url = f"{KOFIC_MOVIE_LIST_URL}?{urlencode(params)}"

    with urlopen(query_url) as response:
        raw = json.loads(response.read().decode("utf-8"))

    movies = []
    for entry in raw.get("movieListResult", {}).get("movieList", []):
        open_dt = entry.get("openDt", "")
        if open_dt and start_date <= open_dt.replace("-", "") <= end_date:
            genres = ", ".join(
                g.get("genreNm", "") for g in entry.get("genres", [])
            )
            movies.append(
                {
                    "code": entry.get("movieCd"),
                    "name": entry.get("movieNm"),
                    "open_date": open_dt,
                    "genre": genres,
                }
            )

    return movies


def fetch_upcoming_releases(api_key: str, days_ahead: int = 14) -> list[dict]:
    """Fetch movies with release dates in the next N days.

    Returns a list of dicts with keys: code, name, open_date, genre.
    Sorted by open_date ascending.
    """
    today = datetime.now()
    start_date = (today + timedelta(days=1)).strftime("%Y%m%d")
    end_date = (today + timedelta(days=days_ahead)).strftime("%Y%m%d")

    params = {
        "key": api_key,
        "openStartDt": start_date[:4],
        "openEndDt": end_date[:4],
        "itemPerPage": "100",
    }
    query_url = f"{KOFIC_MOVIE_LIST_URL}?{urlencode(params)}"

    with urlopen(query_url) as response:
        raw = json.loads(response.read().decode("utf-8"))

    movies = []
    for entry in raw.get("movieListResult", {}).get("movieList", []):
        open_dt = entry.get("openDt", "")
        if open_dt and start_date <= open_dt.replace("-", "") <= end_date:
            genres = ", ".join(
                g.get("genreNm", "") for g in entry.get("genres", [])
            )
            movies.append(
                {
                    "code": entry.get("movieCd"),
                    "name": entry.get("movieNm"),
                    "open_date": open_dt,
                    "genre": genres,
                }
            )

    movies.sort(key=lambda m: m["open_date"])
    return movies
