"""Digest settings — persisted as JSON in data/settings.json."""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path("config/settings.json")


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

    # LLM — per-provider API keys with priority ordering
    llm_provider: str = "openai"  # primary provider (compat)
    llm_model: str = ""  # empty = provider default
    llm_api_key: str = ""  # primary provider key (compat)

    # Priority-ordered list of providers: ["openai", "anthropic", "google"]
    llm_provider_order: list[str] = field(
        default_factory=lambda: ["openai", "anthropic", "google"]
    )
    # Per-provider API keys: {"openai": "sk-...", "anthropic": "sk-...", ...}
    llm_api_keys: dict[str, str] = field(default_factory=dict)
    # Per-provider model overrides: {"openai": "gpt-4o", ...}
    llm_models: dict[str, str] = field(default_factory=dict)

    # Curation preferences (free text, passed to LLM)
    preferences: str = ""

    def active_llm_api_key(self, provider: str) -> str:
        """Get the API key for a provider (per-provider key or legacy fallback)."""
        return self.llm_api_keys.get(provider, "") or (
            self.llm_api_key if provider == self.llm_provider else ""
        )

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
