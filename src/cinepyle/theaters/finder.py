"""Unified nearby theater finder across all chains and indie cinemas."""

import logging
import math

from cinepyle.theaters import cgv, lotte, megabox
from cinepyle.theaters.data_indie import data as indie_theaters

logger = logging.getLogger(__name__)


def _distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Euclidean distance (suitable for nearby comparisons at city scale)."""
    dx = lat1 - lat2
    dy = lon1 - lon2
    return math.sqrt(dx**2 + dy**2)


def find_nearest_theaters(
    latitude: float,
    longitude: float,
    n: int = 5,
) -> list[dict]:
    """Find the N nearest theaters across all chains and indie cinemas.

    Returns a list of dicts with: TheaterName, Distance, Chain, Latitude, Longitude.
    The list is sorted by distance (nearest first).
    """
    all_theaters: list[tuple[float, dict]] = []

    # CGV (static data, always available)
    try:
        for t in cgv.get_theater_list():
            dist = _distance(
                latitude, longitude, float(t["Latitude"]), float(t["Longitude"])
            )
            all_theaters.append(
                (
                    dist,
                    {
                        "TheaterName": t["TheaterName"],
                        "Latitude": t["Latitude"],
                        "Longitude": t["Longitude"],
                        "Chain": "CGV",
                    },
                )
            )
    except Exception:
        logger.exception("Failed to load CGV theaters")

    # Lotte Cinema (API call)
    try:
        for t in lotte.get_theater_list():
            dist = _distance(
                latitude, longitude, float(t["Latitude"]), float(t["Longitude"])
            )
            all_theaters.append(
                (
                    dist,
                    {
                        "TheaterName": t["TheaterName"],
                        "Latitude": t["Latitude"],
                        "Longitude": t["Longitude"],
                        "Chain": "롯데시네마",
                    },
                )
            )
    except Exception:
        logger.exception("Failed to load Lotte Cinema theaters")

    # MegaBox (API call)
    try:
        for t in megabox.get_theater_list():
            dist = _distance(
                latitude, longitude, float(t["Latitude"]), float(t["Longitude"])
            )
            all_theaters.append(
                (
                    dist,
                    {
                        "TheaterName": t["TheaterName"],
                        "Latitude": t["Latitude"],
                        "Longitude": t["Longitude"],
                        "Chain": "메가박스",
                    },
                )
            )
    except Exception:
        logger.exception("Failed to load MegaBox theaters")

    # Indie / CineQ theaters (static data)
    for t in indie_theaters:
        dist = _distance(
            latitude, longitude, float(t["Latitude"]), float(t["Longitude"])
        )
        chain_label = "씨네Q" if t.get("Type") == "cineq" else "독립영화관"
        all_theaters.append(
            (
                dist,
                {
                    "TheaterName": t["TheaterName"],
                    "Latitude": t["Latitude"],
                    "Longitude": t["Longitude"],
                    "Chain": chain_label,
                },
            )
        )

    all_theaters.sort(key=lambda x: x[0])
    return [theater for _, theater in all_theaters[:n]]
