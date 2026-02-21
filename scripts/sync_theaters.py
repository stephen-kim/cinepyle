#!/usr/bin/env python3
"""Standalone theater sync script for GitHub Actions.

Syncs all theater chains (CGV, Lotte, MegaBox, Indie/CineQ) and writes
the result to data/seed/theaters.db.  This replaces the in-container
periodic sync — theater data is now updated centrally via CI and shipped
inside the Docker image.

Supports phased sync to avoid rate limits:
  --phase 1  →  scan days 0–6  (this week)
  --phase 2  →  scan days 7–13 (next week)
  (no flag)  →  scan days 0–13 (full, legacy)

Usage:
    uv run python scripts/sync_theaters.py
    uv run python scripts/sync_theaters.py --phase 1
    uv run python scripts/sync_theaters.py --phase 2
"""

import argparse
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

# Minimum percentage of theaters that must have screen data per chain.
# If a chain falls below this threshold, the sync is considered failed.
_MIN_SCREEN_RATE = 0.9  # 90%

# Chains that have no screen API — exempt from health check
_EXEMPT_CHAINS = {"indie", "cineq"}

_PHASE_RANGES = {
    1: (0, 7),
    2: (7, 14),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase", type=int, choices=[1, 2], default=None,
        help="Sync phase: 1 = days 0-6, 2 = days 7-13",
    )
    args = parser.parse_args()

    if args.phase:
        day_start, day_end = _PHASE_RANGES[args.phase]
        logger.info("Starting theater sync phase %d (days %d–%d)...", args.phase, day_start, day_end - 1)
    else:
        day_start, day_end = 0, None
        logger.info("Starting full theater sync (days 0–13)...")

    db = sync_all_theaters(day_start, day_end)

    total_theaters = len(db.theaters)
    total_screens = sum(len(t.screens) for t in db.theaters)
    last_sync = db.last_sync_at
    now_playing_movies = db.get_now_playing_movies()

    logger.info(
        "Sync complete: %d theaters, %d screens, %d now-playing movies (sync_at=%s)",
        total_theaters,
        total_screens,
        len(now_playing_movies),
        last_sync,
    )

    if total_theaters == 0:
        logger.error("Sync returned 0 theaters — aborting seed update")
        db.close()
        sys.exit(1)

    # Per-chain health check
    chain_stats: dict[str, dict] = {}
    for t in db.theaters:
        stats = chain_stats.setdefault(t.chain, {"total": 0, "with_screens": 0})
        stats["total"] += 1
        if t.screens:
            stats["with_screens"] += 1

    db.close()

    failed_chains: list[str] = []
    for chain, stats in sorted(chain_stats.items()):
        total = stats["total"]
        with_screens = stats["with_screens"]
        rate = with_screens / total if total else 0
        exempt = chain in _EXEMPT_CHAINS
        status = "OK" if rate >= _MIN_SCREEN_RATE or exempt else "FAIL"
        logger.info(
            "  %s: %d/%d theaters with screens (%.0f%%) — %s%s",
            chain, with_screens, total, rate * 100, status,
            " (exempt)" if exempt else "",
        )
        if total > 0 and rate < _MIN_SCREEN_RATE and not exempt:
            failed_chains.append(chain)

    if failed_chains:
        logger.error(
            "Sync FAILED — chains below %.0f%% screen rate: %s",
            _MIN_SCREEN_RATE * 100,
            ", ".join(failed_chains),
        )
        sys.exit(1)

    # Copy the synced DB to seed location
    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB_PATH, SEED_PATH)
    logger.info("Seed DB updated: %s", SEED_PATH)


if __name__ == "__main__":
    main()
