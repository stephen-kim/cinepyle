"""KOFIC movie API client — new releases, search, and movie detail."""

import json
from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen

_KOFIC_BASE = "http://www.kobis.or.kr/kobisopenapi/webservice/rest/movie"

KOFIC_MOVIE_LIST_URL = f"{_KOFIC_BASE}/searchMovieList.json"
KOFIC_MOVIE_INFO_URL = f"{_KOFIC_BASE}/searchMovieInfo.json"


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


def search_movie_by_name(api_key: str, movie_name: str) -> list[dict]:
    """Search KOFIC movie list by name.

    Returns a list of dicts with keys: code, name, name_en, open_date, genre.
    Sorted by openDt descending (most recent first).
    """
    params = {
        "key": api_key,
        "movieNm": movie_name,
        "itemPerPage": "10",
    }
    query_url = f"{KOFIC_MOVIE_LIST_URL}?{urlencode(params)}"

    with urlopen(query_url) as response:
        raw = json.loads(response.read().decode("utf-8"))

    movies = []
    for entry in raw.get("movieListResult", {}).get("movieList", []):
        genres = ", ".join(
            g.get("genreNm", "") for g in entry.get("genres", [])
        )
        movies.append(
            {
                "code": entry.get("movieCd"),
                "name": entry.get("movieNm"),
                "name_en": entry.get("movieNmEn", ""),
                "open_date": entry.get("openDt", ""),
                "genre": genres,
            }
        )

    # Most recent first
    movies.sort(key=lambda m: m.get("open_date", ""), reverse=True)
    return movies


def fetch_movie_info(api_key: str, movie_cd: str) -> dict | None:
    """Fetch detailed movie info from KOFIC.

    Returns dict with keys: title, title_en, runtime, open_date,
    directors (list[str]), actors (list[dict{name,cast}]),
    genres (list[str]), nations (list[str]), rating (str).
    Returns None if movie not found.
    """
    params = {"key": api_key, "movieCd": movie_cd}
    query_url = f"{KOFIC_MOVIE_INFO_URL}?{urlencode(params)}"

    with urlopen(query_url) as response:
        raw = json.loads(response.read().decode("utf-8"))

    info = raw.get("movieInfoResult", {}).get("movieInfo")
    if not info:
        return None

    directors = [d.get("peopleNm", "") for d in info.get("directors", []) if d.get("peopleNm")]
    actors = [
        {"name": a.get("peopleNm", ""), "cast": a.get("cast", "")}
        for a in info.get("actors", [])
        if a.get("peopleNm")
    ]
    genres = [g.get("genreNm", "") for g in info.get("genres", []) if g.get("genreNm")]
    nations = [n.get("nationNm", "") for n in info.get("nations", []) if n.get("nationNm")]

    audits = info.get("audits", [])
    rating = audits[0].get("watchGradeNm", "") if audits else ""

    return {
        "title": info.get("movieNm", ""),
        "title_en": info.get("movieNmEn", ""),
        "runtime": info.get("showTm", ""),
        "open_date": info.get("openDt", ""),
        "directors": directors,
        "actors": actors,
        "genres": genres,
        "nations": nations,
        "rating": rating,
    }
