"""Unified nearby theater finder across all chains and indie cinemas."""

import logging
import math

from cinepyle.theaters import cgv, cineq, lotte, megabox
from cinepyle.theaters.data_indie import data as indie_theaters

logger = logging.getLogger(__name__)

# Display name → chain key mapping (for booking)
_CHAIN_DISPLAY_TO_KEY = {
    "CGV": "cgv",
    "롯데시네마": "lotte",
    "메가박스": "megabox",
    "씨네Q": "cineq",
    "독립영화관": "indie",
}


def _distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Euclidean distance (suitable for nearby comparisons at city scale)."""
    dx = lat1 - lat2
    dy = lon1 - lon2
    return math.sqrt(dx**2 + dy**2)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in kilometers (accurate for display)."""
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearest_theaters(
    latitude: float,
    longitude: float,
    n: int = 5,
) -> list[dict]:
    """Find the N nearest theaters across all chains and indie cinemas.

    Returns a list of dicts with:
        TheaterName, Chain, ChainKey, TheaterCode, RegionCode,
        Latitude, Longitude, DistanceKm
    The list is sorted by distance (nearest first).
    """
    all_theaters: list[tuple[float, dict]] = []

    def _add(theaters: list[dict], chain_display: str, chain_key: str) -> None:
        for t in theaters:
            lat = float(t["Latitude"])
            lon = float(t["Longitude"])
            dist = _distance(latitude, longitude, lat, lon)
            dist_km = _haversine_km(latitude, longitude, lat, lon)

            theater_code = str(
                t.get("TheaterCode", t.get("TheaterID", t.get("brchNo", "")))
            )
            region_code = t.get("RegionCode", "")

            all_theaters.append(
                (
                    dist,
                    {
                        "TheaterName": t["TheaterName"],
                        "Chain": chain_display,
                        "ChainKey": chain_key,
                        "TheaterCode": theater_code,
                        "RegionCode": region_code,
                        "Latitude": lat,
                        "Longitude": lon,
                        "DistanceKm": round(dist_km, 1),
                    },
                )
            )

    # CGV (static data, always available)
    try:
        _add(cgv.get_theater_list(), "CGV", "cgv")
    except Exception:
        logger.exception("Failed to load CGV theaters")

    # Lotte Cinema (API call)
    try:
        _add(lotte.get_theater_list(), "롯데시네마", "lotte")
    except Exception:
        logger.exception("Failed to load Lotte Cinema theaters")

    # MegaBox (API call)
    try:
        _add(megabox.get_theater_list(), "메가박스", "megabox")
    except Exception:
        logger.exception("Failed to load MegaBox theaters")

    # CineQ (static data)
    try:
        _add(cineq.get_theater_list(), "씨네Q", "cineq")
    except Exception:
        logger.exception("Failed to load CineQ theaters")

    # Indie theaters (static data — no booking available)
    for t in indie_theaters:
        lat = float(t["Latitude"])
        lon = float(t["Longitude"])
        dist = _distance(latitude, longitude, lat, lon)
        dist_km = _haversine_km(latitude, longitude, lat, lon)
        all_theaters.append(
            (
                dist,
                {
                    "TheaterName": t["TheaterName"],
                    "Chain": "독립영화관",
                    "ChainKey": "indie",
                    "TheaterCode": "",
                    "RegionCode": "",
                    "Latitude": lat,
                    "Longitude": lon,
                    "DistanceKm": round(dist_km, 1),
                },
            )
        )

    all_theaters.sort(key=lambda x: x[0])
    return [theater for _, theater in all_theaters[:n]]
