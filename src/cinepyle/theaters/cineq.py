"""CineQ (씨네Q) theater data access and schedule fetching.

CineQ provides a server-rendered schedule via POST to /Theater/MovieTable2.
The response is HTML which we parse with BeautifulSoup.
No Playwright needed.
"""

import math
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from cinepyle.theaters.data_cineq import data

BASE_URL = "https://www.cineq.co.kr"
SCHEDULE_URL = f"{BASE_URL}/Theater/MovieTable2"


def get_theater_list() -> list[dict]:
    """Return the static list of CineQ theaters."""
    return data


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


def get_movie_schedule(theater_code: str) -> dict:
    """Fetch today's movie schedule for a CineQ theater.

    Returns a dict: {movie_title: {"Name": str, "Schedules": [{"StartTime": str, "RemainingSeat": str}]}}
    """
    today = datetime.now().strftime("%Y%m%d")
    response = requests.post(
        SCHEDULE_URL,
        data={"TheaterCode": theater_code, "PlayDate": today},
        timeout=10,
    )
    response.raise_for_status()

    return _parse_schedule_html(response.text)


def _parse_schedule_html(html: str) -> dict:
    """Parse the CineQ schedule HTML into a structured dict."""
    soup = BeautifulSoup(html, "lxml")
    movie_info: dict = {}

    for movie_block in soup.select("div.each-movie-time"):
        title_el = movie_block.select_one("div.title")
        if not title_el:
            continue

        # Extract movie title (text after the rating span)
        title_text = title_el.get_text(strip=True)
        # Remove rating prefix like "12", "15", "전체", "R"
        rating_span = title_el.select_one("span")
        if rating_span:
            title_text = title_text.replace(rating_span.get_text(strip=True), "", 1).strip()

        if not title_text:
            continue

        schedules = []
        for time_div in movie_block.select("div.time"):
            link = time_div.select_one("a")
            if not link:
                continue

            time_text = link.get_text(strip=True)
            # Extract start time (HH:MM)
            m = re.match(r"(\d{2}:\d{2})", time_text)
            if not m:
                continue

            start_time = m.group(1)

            # Extract seat status
            seat_span = time_div.select_one("span.seats-status")
            seat_status = seat_span.get_text(strip=True) if seat_span else ""

            # Extract remaining seats if available
            seat_match = re.search(r"(\d+)\s*석", seat_status)
            remaining = seat_match.group(1) if seat_match else seat_status

            schedules.append({
                "StartTime": start_time,
                "RemainingSeat": remaining,
            })

        if schedules:
            movie_info[title_text] = {
                "Name": title_text,
                "Schedules": schedules,
            }

    return movie_info
