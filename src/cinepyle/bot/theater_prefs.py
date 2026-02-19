"""User theater preferences — persisted as JSON."""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

PREFS_PATH = Path("data/theater_preferences.json")


@dataclass
class TheaterPreferences:
    """Preferred theaters and screen types for showtime queries.

    preferred_theaters: theater keys like "cgv:0013", "lotte:1009"
    preferred_screen_types: screen type strings like "imax", "4dx"
    """

    preferred_theaters: list[str] = field(default_factory=list)
    preferred_screen_types: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> "TheaterPreferences":
        if not PREFS_PATH.exists():
            return cls()
        try:
            raw = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
            known = {k for k in cls.__dataclass_fields__}
            filtered = {k: v for k, v in raw.items() if k in known}
            return cls(**filtered)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupt theater preferences, using defaults")
            return cls()

    def save(self) -> None:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PREFS_PATH.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def add_theater(self, theater_key: str) -> bool:
        if theater_key not in self.preferred_theaters:
            self.preferred_theaters.append(theater_key)
            return True
        return False

    def remove_theater(self, theater_key: str) -> bool:
        if theater_key in self.preferred_theaters:
            self.preferred_theaters.remove(theater_key)
            return True
        return False

    def add_screen_type(self, screen_type: str) -> bool:
        if screen_type not in self.preferred_screen_types:
            self.preferred_screen_types.append(screen_type)
            return True
        return False

    def remove_screen_type(self, screen_type: str) -> bool:
        if screen_type in self.preferred_screen_types:
            self.preferred_screen_types.remove(screen_type)
            return True
        return False
