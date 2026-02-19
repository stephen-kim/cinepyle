"""Unified nearby theater finder using the local TheaterDatabase.

Uses pre-synced theater data (lat/lon) from the SQLite DB instead of
making live API calls, which avoids N+1 HTTP requests and hangs.
"""

import logging
import math

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
    chain_filter: str = "",
) -> list[dict]:
    """Find the N nearest theaters across all chains.

    Uses the local TheaterDatabase (SQLite) which already has lat/lon for
    all theaters.  No HTTP calls are made — instant results.

    Args:
        latitude: User's latitude.
        longitude: User's longitude.
        n: Max number of results.
        chain_filter: Optional chain name filter (e.g. "메가박스", "CGV").

    Returns:
        List of dicts with: TheaterName, Distance, Chain, Latitude, Longitude.
        Sorted by distance (nearest first).
    """
    from cinepyle.theaters.models import TheaterDatabase

    db = TheaterDatabase.load()
    try:
        all_theaters: list[tuple[float, dict]] = []

        for t in db.theaters:
            # Skip theaters without coordinates
            if not t.latitude or not t.longitude:
                continue

            # Apply chain filter if specified
            if chain_filter:
                cf = chain_filter.lower()
                chain_lower = t.chain.lower()
                name_lower = t.name.lower()
                if cf not in chain_lower and cf not in name_lower:
                    continue

            dist = _distance(latitude, longitude, t.latitude, t.longitude)
            all_theaters.append(
                (
                    dist,
                    {
                        "TheaterName": t.name,
                        "Latitude": t.latitude,
                        "Longitude": t.longitude,
                        "Chain": t.chain,
                    },
                )
            )

        all_theaters.sort(key=lambda x: x[0])
        return [theater for _, theater in all_theaters[:n]]
    finally:
        db.close()
