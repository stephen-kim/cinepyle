"""Digest settings — persisted as JSON in data/settings.json."""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path("data/settings.json")


@dataclass
class DigestSettings:
    """All configurable digest parameters."""

    # Sources
    sources_enabled: dict[str, bool] = field(
        default_factory=lambda: {"google": True, "cine21": True, "watcha": True}
    )

    # Schedule
    schedule_enabled: bool = True
    schedule_hour: int = 9  # KST (0-23)
    schedule_minute: int = 0

    # LLM
    llm_provider: str = "openai"  # "openai" | "anthropic" | "google"
    llm_model: str = ""  # empty = provider default
    llm_api_key: str = ""

    # Curation preferences (free text, passed to LLM)
    preferences: str = ""

    @classmethod
    def load(cls) -> "DigestSettings":
        """Load from JSON file. Returns defaults if file doesn't exist."""
        if not SETTINGS_PATH.exists():
            return cls()
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            # Only accept known fields
            known = {k for k in cls.__dataclass_fields__}
            filtered = {k: v for k, v in raw.items() if k in known}
            return cls(**filtered)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupt settings file, using defaults")
            return cls()

    def save(self) -> None:
        """Persist to JSON file."""
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
