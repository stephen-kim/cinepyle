"""Screen alert settings — persisted as JSON."""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path("config/screen_alert_settings.json")


@dataclass
class ScreenAlertSettings:
    """Configuration for screen-based notifications.

    Each watched screen is stored as "chain:theater_code:screen_id".
    """

    watched_screens: list[str] = field(default_factory=list)
    alerts_enabled: bool = True
    check_interval_minutes: int = 30

    @classmethod
    def load(cls) -> "ScreenAlertSettings":
        """Load from JSON file. Returns defaults if file doesn't exist."""
        if not SETTINGS_PATH.exists():
            return cls()
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            known = {k for k in cls.__dataclass_fields__}
            filtered = {k: v for k, v in raw.items() if k in known}
            return cls(**filtered)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupt screen alert settings, using defaults")
            return cls()

    def save(self) -> None:
        """Persist to JSON file."""
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def is_watching(self, screen_key: str) -> bool:
        """Check if a screen is being watched."""
        return screen_key in self.watched_screens
