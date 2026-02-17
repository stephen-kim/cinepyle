"""MegaBox theater data access and schedule fetching."""

import math
from datetime import datetime

import requests


BASE_URL = "https://www.megabox.co.kr/on/oh/ohc/Brch/schedulePage.do"


def get_theater_list() -> list[dict]:
    """Fetch all MegaBox theaters that have screenings today."""
    today = datetime.now().strftime("%Y%m%d")
    params = {"masterType": "brch", "playDe": today}
    res = requests.post(BASE_URL, data=params, timeout=10).json()
    items = res.get("megaMap", {}).get("movieFormList", [])

    seen_ids: set[str] = set()
    branch_ids = []
    for s in items:
        bid = str(s["brchNo"])
        if bid not in seen_ids:
            seen_ids.add(bid)
            branch_ids.append(bid)

    theaters = []
    for bid in branch_ids:
        params = {
            "masterType": "brch",
            "brchNo": bid,
            "brchNo1": bid,
            "firstAt": "Y",
        }
        response = requests.post(BASE_URL, data=params, timeout=10).json()
        info = response.get("megaMap", {}).get("brchInfo")
        if info:
            theaters.append(
                {
                    "TheaterName": f"{info.get('brchNm')} 메가박스",
                    "TheaterID": info.get("brchNo"),
                    "Latitude": info.get("brchLat"),
                    "Longitude": info.get("brchLon"),
                }
            )

    return theaters


def filter_nearest(
    theater_list: list[dict],
    latitude: float,
    longitude: float,
    n: int = 3,
) -> list[dict]:
    """Return the N nearest theaters from the list."""
    with_distance = []
    for theater in theater_list:
        dx = latitude - float(theater["Latitude"])
        dy = longitude - float(theater["Longitude"])
        dist = math.sqrt(dx**2 + dy**2)
        with_distance.append((dist, theater))

    with_distance.sort(key=lambda x: x[0])
    return [theater for _, theater in with_distance[:n]]


def get_movie_schedule(theater_id: str) -> dict:
    """Fetch today's movie schedule for a MegaBox theater.

    Returns a dict: {movie_no: {"Name": str, "Schedules": [{"StartTime": str, "RemainingSeat": str}]}}
    """
    today = datetime.now().strftime("%Y%m%d")
    params = {
        "masterType": "brch",
        "brchNo": theater_id,
        "brchNo1": theater_id,
        "firstAt": "Y",
        "playDe": today,
    }
    json_content = requests.post(BASE_URL, data=params, timeout=10).json()
    movie_id_to_info: dict = {}

    for entry in json_content.get("megaMap", {}).get("movieFormList", []):
        movie_id_to_info.setdefault(entry.get("movieNo"), {})[
            "Name"
        ] = entry.get("movieNm")

    for entry in json_content.get("megaMap", {}).get("movieFormList", []):
        schedules = movie_id_to_info[entry.get("movieNo")].setdefault(
            "Schedules", []
        )
        schedule = {
            "StartTime": str(entry.get("playStartTime")),
            "RemainingSeat": str(int(entry.get("restSeatCnt", 0))),
        }
        schedules.append(schedule)

    return movie_id_to_info
