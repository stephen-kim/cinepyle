"""Theater sync settings — persisted as JSON."""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path("data/sync_settings.json")


@dataclass
class SyncSettings:
    """Configuration for periodic theater synchronisation."""

    sync_enabled: bool = True
    sync_interval_days: int = 1  # 1–30

    @classmethod
    def load(cls) -> "SyncSettings":
        """Load from JSON file. Returns defaults if file doesn't exist."""
        if not SETTINGS_PATH.exists():
            return cls()
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            known = {k for k in cls.__dataclass_fields__}
            filtered = {k: v for k, v in raw.items() if k in known}
            return cls(**filtered)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupt sync settings, using defaults")
            return cls()

    def save(self) -> None:
        """Persist to JSON file."""
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
