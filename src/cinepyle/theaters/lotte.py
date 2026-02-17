"""Lotte Cinema theater data access and schedule fetching."""

import json
import math
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import urlopen


BASE_URL = "http://www.lottecinema.co.kr"
CINEMA_DATA_URL = f"{BASE_URL}/LCWS/Cinema/CinemaData.aspx"
TICKETING_URL = f"{BASE_URL}/LCWS/Ticketing/TicketingData.aspx"


def _make_payload(**kwargs: str) -> bytes:
    param_list = {"channelType": "MW", "osType": "", "osVersion": "", **kwargs}
    data = {"ParamList": json.dumps(param_list)}
    return urlencode(data).encode("utf8")


def _read_json(fp) -> dict:
    content = fp.read().decode("utf8")
    return json.loads(content)


def get_theater_list() -> list[dict]:
    """Fetch all Lotte Cinema theaters."""
    payload = _make_payload(MethodName="GetCinemaItems")
    with urlopen(CINEMA_DATA_URL, data=payload) as fin:
        json_content = _read_json(fin)
        items = json_content.get("Cinemas", {}).get("Items", [])
        items = [x for x in items if x["DivisionCode"] != 2]
        return [
            {
                "TheaterName": f"{entry.get('CinemaNameKR')} 롯데시네마",
                "TheaterID": (
                    f"{entry.get('DivisionCode')}|"
                    f"{entry.get('SortSequence')}|"
                    f"{entry.get('CinemaID')}"
                ),
                "TheaterDCODE": entry.get("DetailDivisionCode"),
                "Longitude": entry.get("Longitude"),
                "Latitude": entry.get("Latitude"),
            }
            for entry in items
        ]


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
    """Fetch today's movie schedule for a Lotte Cinema theater.

    Returns a dict: {movie_code: {"Name": str, "Schedules": [{"StartTime": str, "RemainingSeat": str}]}}
    """
    today = datetime.now().strftime("%Y-%m-%d")
    payload = _make_payload(
        MethodName="GetPlaySequence",
        playDate=today,
        cinemaID=theater_id,
        representationMovieCode="",
    )
    with urlopen(TICKETING_URL, data=payload) as fin:
        json_content = _read_json(fin)
        movie_id_to_info: dict = {}

        for entry in json_content.get("PlaySeqsHeader", {}).get("Items", []):
            movie_id_to_info.setdefault(entry.get("MovieCode"), {})[
                "Name"
            ] = entry.get("MovieNameKR")

        for entry in json_content.get("PlaySeqs", {}).get("Items", []):
            schedules = movie_id_to_info[entry.get("MovieCode")].setdefault(
                "Schedules", []
            )
            schedule = {
                "StartTime": str(entry.get("StartTime")),
                "RemainingSeat": str(
                    int(entry.get("TotalSeatCount", 0))
                    - int(entry.get("BookingSeatCount", 0))
                ),
            }
            schedules.append(schedule)

        return movie_id_to_info
