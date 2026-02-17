"""Daily theater list synchronisation job.

Fetches theater data from all chains (CGV, CineQ, Lotte, Megabox,
indie cinemas) and persists the combined list to the settings DB.
The dashboard search endpoint reads from this cached list instead
of making live API calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

import requests
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

_SEED_FILE = Path(__file__).resolve().parent.parent / "theaters" / "seed_theaters.json"


# ------------------------------------------------------------------
# Seed data (initial load before first sync)
# ------------------------------------------------------------------


def load_seed_theaters() -> list[dict]:
    """Load the bundled seed theater list for first-run bootstrap."""
    if _SEED_FILE.exists():
        try:
            return json.loads(_SEED_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load seed theaters from %s", _SEED_FILE)
    return []


# ------------------------------------------------------------------
# Fetch helpers
# ------------------------------------------------------------------


def _fetch_all_theaters() -> list[dict]:
    """Build a merged theater list across all chains (blocking I/O).

    Returns a list of dicts with keys:
        chain_key, theater_code, region_code, name
    """
    all_theaters: list[dict] = []

    # ── CGV (static) ──
    try:
        from cinepyle.theaters.data_cgv import data as cgv_data

        for t in cgv_data:
            all_theaters.append({
                "chain_key": "cgv",
                "theater_code": t["TheaterCode"],
                "region_code": t.get("RegionCode", ""),
                "name": t["TheaterName"],
            })
    except Exception:
        logger.exception("Failed to load CGV theaters")

    # ── CineQ (static) ──
    try:
        from cinepyle.theaters.data_cineq import data as cineq_data

        for t in cineq_data:
            all_theaters.append({
                "chain_key": "cineq",
                "theater_code": t["TheaterCode"],
                "region_code": "",
                "name": t["TheaterName"],
            })
    except Exception:
        logger.exception("Failed to load CineQ theaters")

    # ── 독립영화관 (static) ──
    try:
        from cinepyle.theaters.data_indie import data as indie_data

        for t in indie_data:
            all_theaters.append({
                "chain_key": "indie",
                "theater_code": "",
                "region_code": "",
                "name": t["TheaterName"],
            })
    except Exception:
        logger.exception("Failed to load indie theaters")

    # ── Lotte Cinema (API) ──
    try:
        from cinepyle.theaters import lotte

        for t in lotte.get_theater_list():
            all_theaters.append({
                "chain_key": "lotte",
                "theater_code": str(t.get("TheaterID", "")),
                "region_code": "",
                "name": t["TheaterName"],
            })
    except Exception:
        logger.exception("Failed to fetch Lotte theaters")

    # ── Megabox (API — lightweight single call) ──
    try:
        mega_url = "https://www.megabox.co.kr/on/oh/ohc/Brch/schedulePage.do"
        mega_res = requests.post(
            mega_url,
            data={"masterType": "brch", "playDe": datetime.now().strftime("%Y%m%d")},
            timeout=15,
        ).json()
        mega_items = mega_res.get("megaMap", {}).get("movieFormList", [])

        seen: dict[str, str] = {}  # brchNo → brchNm
        for s in mega_items:
            bid = str(s.get("brchNo", ""))
            if bid and bid not in seen:
                seen[bid] = s.get("brchNm", bid)

        for bid, bname in seen.items():
            all_theaters.append({
                "chain_key": "megabox",
                "theater_code": bid,
                "region_code": "",
                "name": f"{bname} 메가박스",
            })
    except Exception:
        logger.exception("Failed to fetch Megabox theaters")

    return all_theaters


# ------------------------------------------------------------------
# Telegram JobQueue callback
# ------------------------------------------------------------------


async def sync_theaters_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetch all theater lists and persist to settings DB."""
    try:
        from cinepyle.dashboard.settings_manager import SettingsManager

        all_theaters = await asyncio.to_thread(_fetch_all_theaters)
        mgr = SettingsManager.get_instance()
        await mgr.sync_theater_list(all_theaters)
        logger.info("Theater sync complete: %d theaters cached", len(all_theaters))
    except Exception:
        logger.exception("Theater sync failed")
