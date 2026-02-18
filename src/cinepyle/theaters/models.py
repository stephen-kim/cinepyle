"""Theater and screen data models with JSON persistence."""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

THEATERS_PATH = Path("data/theaters.json")


# ---------------------------------------------------------------------------
# Screen type constants
# ---------------------------------------------------------------------------

SCREEN_TYPE_NORMAL = "normal"
SCREEN_TYPE_IMAX = "imax"
SCREEN_TYPE_4DX = "4dx"
SCREEN_TYPE_SCREENX = "screenx"
SCREEN_TYPE_DOLBY_ATMOS = "dolby_atmos"
SCREEN_TYPE_DOLBY_CINEMA = "dolby_cinema"
SCREEN_TYPE_SUPERPLEX = "superplex"
SCREEN_TYPE_CHARLOTTE = "charlotte"
SCREEN_TYPE_COMFORT = "comfort"
SCREEN_TYPE_BOUTIQUE = "boutique"
SCREEN_TYPE_RECLINER = "recliner"
SCREEN_TYPE_PREMIUM = "premium"

SPECIAL_TYPES: set[str] = {
    SCREEN_TYPE_IMAX,
    SCREEN_TYPE_4DX,
    SCREEN_TYPE_SCREENX,
    SCREEN_TYPE_DOLBY_ATMOS,
    SCREEN_TYPE_DOLBY_CINEMA,
    SCREEN_TYPE_SUPERPLEX,
    SCREEN_TYPE_CHARLOTTE,
    SCREEN_TYPE_BOUTIQUE,
    SCREEN_TYPE_PREMIUM,
}

# CGV tcscnsGradNm (screen grade name) → type
CGV_GRADE_NAME_MAP: dict[str, str] = {
    "아이맥스": SCREEN_TYPE_IMAX,
    "IMAX": SCREEN_TYPE_IMAX,
    "4DX": SCREEN_TYPE_4DX,
    "SCREENX": SCREEN_TYPE_SCREENX,
    "DOLBY ATMOS": SCREEN_TYPE_DOLBY_ATMOS,
    "돌비 애트모스": SCREEN_TYPE_DOLBY_ATMOS,
}

# CGV rcmGradList gradCd → type
CGV_GRAD_CD_MAP: dict[str, str] = {
    "02": SCREEN_TYPE_4DX,
    "03": SCREEN_TYPE_IMAX,
    "04": SCREEN_TYPE_SCREENX,
    "07": SCREEN_TYPE_DOLBY_ATMOS,
}

# Lotte ScreenDivisionCode → type
LOTTE_SCREEN_TYPE_MAP: dict[str, str] = {
    "100": SCREEN_TYPE_NORMAL,
    "300": SCREEN_TYPE_CHARLOTTE,
    "301": SCREEN_TYPE_CHARLOTTE,  # 샤롯데 프라이빗
    "901": SCREEN_TYPE_PREMIUM,    # 광음시네마
    "902": SCREEN_TYPE_PREMIUM,    # 광음LED
    "940": SCREEN_TYPE_SUPERPLEX,
    "960": SCREEN_TYPE_NORMAL,     # 씨네패밀리
    "980": SCREEN_TYPE_PREMIUM,    # 수퍼LED(일반)
    "986": SCREEN_TYPE_RECLINER,
    "988": SCREEN_TYPE_RECLINER,   # 수퍼LED(리클)
}

# MegaBox theabKindCd → type
MEGABOX_SCREEN_TYPE_MAP: dict[str, str] = {
    "NOR": SCREEN_TYPE_NORMAL,
    "CFT": SCREEN_TYPE_COMFORT,
    "DBC": SCREEN_TYPE_DOLBY_CINEMA,
    "DVA": SCREEN_TYPE_DOLBY_CINEMA,  # Dolby Vision+Atmos
    "LUMINEON": SCREEN_TYPE_PREMIUM,  # MEGA LED
    "MKB": SCREEN_TYPE_PREMIUM,       # 만경관
    "MX": SCREEN_TYPE_DOLBY_ATMOS,
    "MX4D": SCREEN_TYPE_4DX,          # MX4D motion seats
    "RCL": SCREEN_TYPE_RECLINER,
    "TBQ": SCREEN_TYPE_BOUTIQUE,      # 부티크
    "TBS": SCREEN_TYPE_BOUTIQUE,      # 부티크 스위트
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Screen:
    """A single screen (hall) within a theater."""

    screen_id: str  # unique within theater (e.g., "018", "100_21관")
    name: str  # display name (e.g., "IMAX관", "1관 (Laser)")
    screen_type: str  # normalized type code
    seat_count: int = 0
    is_special: bool = False


@dataclass
class Theater:
    """A cinema theater belonging to a chain."""

    chain: str  # "cgv" | "lotte" | "megabox" | "cineq" | "indie"
    theater_code: str  # unique per chain
    name: str  # display name (e.g., "CGV용산아이파크몰")
    address: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    screens: list[Screen] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Unique key across all chains."""
        return f"{self.chain}:{self.theater_code}"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


class TheaterDatabase:
    """In-memory theater database with JSON persistence.

    Follows the same load/save pattern as DigestSettings.
    """

    def __init__(self, theaters: list[Theater] | None = None) -> None:
        self.theaters: list[Theater] = theaters or []
        self._by_key: dict[str, Theater] = {}
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._by_key = {t.key: t for t in self.theaters}

    def get(self, chain: str, theater_code: str) -> Theater | None:
        return self._by_key.get(f"{chain}:{theater_code}")

    def get_by_chain(self, chain: str) -> list[Theater]:
        return sorted(
            [t for t in self.theaters if t.chain == chain],
            key=lambda t: t.name,
        )

    def update_chain(self, chain: str, theaters: list[Theater]) -> None:
        """Replace all theaters for a given chain. Partial-update safe."""
        self.theaters = [t for t in self.theaters if t.chain != chain]
        self.theaters.extend(theaters)
        self._rebuild_index()

    @classmethod
    def load(cls) -> "TheaterDatabase":
        """Load from JSON file. Returns empty DB if file doesn't exist."""
        if not THEATERS_PATH.exists():
            return cls()
        try:
            raw = json.loads(THEATERS_PATH.read_text(encoding="utf-8"))
            theaters = []
            for t_data in raw.get("theaters", []):
                screens_data = t_data.pop("screens", [])
                screens = [Screen(**s) for s in screens_data]
                theaters.append(Theater(**t_data, screens=screens))
            return cls(theaters)
        except (json.JSONDecodeError, TypeError, KeyError):
            logger.warning("Corrupt theaters.json, starting fresh")
            return cls()

    def save(self) -> None:
        """Persist to JSON file."""
        THEATERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {"theaters": [asdict(t) for t in self.theaters]}
        THEATERS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("Saved %d theaters to %s", len(self.theaters), THEATERS_PATH)
