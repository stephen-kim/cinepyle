#!/usr/bin/env python3
"""Standalone theater sync script for GitHub Actions.

Syncs all theater chains (CGV, Lotte, MegaBox, Indie/CineQ) and writes
the result to data/seed/theaters.db.  This replaces the in-container
periodic sync — theater data is now updated centrally via CI and shipped
inside the Docker image.

Usage:
    uv run python scripts/sync_theaters.py
"""

import logging
import shutil
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cinepyle.theaters.sync import sync_all_theaters

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DB_PATH = Path("data/theaters.db")
SEED_PATH = Path("seed/theaters.db")


def main() -> None:
    logger.info("Starting theater sync...")
    db = sync_all_theaters()

    total_theaters = len(db.theaters)
    total_screens = sum(len(t.screens) for t in db.theaters)
    last_sync = db.last_sync_at
    now_playing_movies = db.get_now_playing_movies()
    db.close()

    logger.info(
        "Sync complete: %d theaters, %d screens, %d now-playing movies (sync_at=%s)",
        total_theaters,
        total_screens,
        len(now_playing_movies),
        last_sync,
    )

    if total_theaters == 0:
        logger.error("Sync returned 0 theaters — aborting seed update")
        sys.exit(1)

    # Copy the synced DB to seed location
    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB_PATH, SEED_PATH)
    logger.info("Seed DB updated: %s", SEED_PATH)


if __name__ == "__main__":
    main()
