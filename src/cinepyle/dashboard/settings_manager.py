"""Central settings mediator for the cinepyle dashboard.

Singleton that bridges the SQLite settings store, the .env config
fallback, and the running Telegram bot (for live job rescheduling).
"""

from __future__ import annotations

import json
import logging

from telegram.ext import Application

from cinepyle.config import TELEGRAM_CHAT_ID
from cinepyle.dashboard.settings_store import SettingsStore

logger = logging.getLogger(__name__)


class SettingsManager:
    """Singleton settings manager with in-memory cache."""

    _instance: SettingsManager | None = None

    def __init__(self, store: SettingsStore) -> None:
        self.store = store
        self._cache: dict[str, str] = {}
        self._app: Application | None = None

    @classmethod
    async def create(cls, db_path: str) -> SettingsManager:
        """Create and initialise the singleton."""
        store = SettingsStore(db_path)
        instance = cls(store)
        instance._cache = await store.get_all()
        cls._instance = instance
        logger.info("SettingsManager loaded %d settings", len(instance._cache))
        return instance

    @classmethod
    def get_instance(cls) -> SettingsManager:
        """Return the initialised singleton. Raises if not yet created."""
        if cls._instance is None:
            raise RuntimeError("SettingsManager not initialised")
        return cls._instance

    # ------------------------------------------------------------------
    # Telegram app reference (for job rescheduling)
    # ------------------------------------------------------------------

    def set_telegram_app(self, app: Application) -> None:
        self._app = app

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------

    def get(self, key: str, default: str = "") -> str:
        """Get a setting from the in-memory cache."""
        return self._cache.get(key, default)

    def has(self, key: str) -> bool:
        return key in self._cache

    async def set(self, key: str, value: str, encrypted: bool = False) -> None:
        """Persist a setting and update cache."""
        await self.store.set(key, value, encrypted=encrypted)
        self._cache[key] = value

    async def set_many(
        self, items: dict[str, str], encrypted: bool = False
    ) -> None:
        """Persist multiple settings."""
        for key, value in items.items():
            await self.store.set(key, value, encrypted=encrypted)
            self._cache[key] = value

    # ------------------------------------------------------------------
    # Job rescheduling
    # ------------------------------------------------------------------

    async def reschedule_job(
        self,
        job_name: str,
        callback,
        new_interval: int,
    ) -> None:
        """Remove and re-register a repeating job with a new interval."""
        if self._app is None:
            logger.warning("Cannot reschedule: telegram app not set")
            return

        jq = self._app.job_queue
        for job in jq.get_jobs_by_name(job_name):
            job.schedule_removal()
            logger.info("Removed old job %s", job_name)

        jq.run_repeating(
            callback,
            interval=new_interval,
            first=10,
            data=TELEGRAM_CHAT_ID,
            name=job_name,
        )
        logger.info("Rescheduled %s with interval=%ds", job_name, new_interval)

    # ------------------------------------------------------------------
    # Engine reset (when LLM / credential settings change)
    # ------------------------------------------------------------------

    def reset_engines(self) -> None:
        """Reset cached HealingEngine singletons so they pick up new config."""
        modules_to_reset = [
            "cinepyle.scrapers.cgv",
            "cinepyle.scrapers.watcha",
            "cinepyle.theaters.cgv",
        ]
        import sys

        for mod_name in modules_to_reset:
            mod = sys.modules.get(mod_name)
            if mod and hasattr(mod, "_engine"):
                mod._engine = None
                logger.info("Reset _engine in %s", mod_name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_llm_priority(self) -> list[str]:
        """Return the LLM provider priority list."""
        raw = self.get("llm_priority", "")
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        return ["anthropic", "openai", "gemini"]

    def get_imax_monitor_theaters(self) -> list[dict]:
        """Return the list of IMAX monitor theater configs.

        Each dict has keys: code, region, name.
        """
        raw = self.get("imax_monitor_theaters", "")
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        return []

    def get_preferred_theaters(self) -> list[dict]:
        """Return the list of preferred theaters for booking.

        Each dict has keys: chain_key, theater_code, region_code, name.
        """
        raw = self.get("preferred_theaters", "")
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        return []

    # ------------------------------------------------------------------
    # Theater list cache (daily sync)
    # ------------------------------------------------------------------

    async def sync_theater_list(self, theaters: list[dict]) -> None:
        """Persist the full theater list to DB."""
        await self.set(
            "cached_theater_list",
            json.dumps(theaters, ensure_ascii=False),
        )

    def get_cached_theater_list(self) -> list[dict]:
        """Return the cached theater list from DB.

        Each dict has keys: chain_key, theater_code, region_code, name.
        """
        raw = self.get("cached_theater_list", "")
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        return []

    async def close(self) -> None:
        await self.store.close()
        SettingsManager._instance = None
