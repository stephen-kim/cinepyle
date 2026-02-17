"""SQLite-backed persistent settings store.

Follows the same aiosqlite lazy-init pattern as notifications/store.py.
Credentials are encrypted at rest using Fernet symmetric encryption.
"""

import logging
import os
from datetime import datetime, timezone

import aiosqlite
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    encrypted   INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);
"""


def _load_or_generate_fernet_key(env_key: str, fallback_path: str) -> bytes:
    """Load Fernet key from env or generate + persist one."""
    from cinepyle.config import SETTINGS_ENCRYPTION_KEY

    if SETTINGS_ENCRYPTION_KEY:
        return SETTINGS_ENCRYPTION_KEY.encode()

    if os.path.exists(fallback_path):
        with open(fallback_path, "rb") as f:
            return f.read().strip()

    key = Fernet.generate_key()
    os.makedirs(os.path.dirname(fallback_path) or ".", exist_ok=True)
    with open(fallback_path, "wb") as f:
        f.write(key)
    logger.info("Generated new settings encryption key at %s", fallback_path)
    return key


class SettingsStore:
    """Async SQLite store for dashboard settings."""

    def __init__(self, db_path: str, fernet_key: bytes | None = None) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        if fernet_key is None:
            key_path = os.path.join(os.path.dirname(db_path) or ".", ".settings_key")
            fernet_key = _load_or_generate_fernet_key("SETTINGS_ENCRYPTION_KEY", key_path)
        self._fernet = Fernet(fernet_key)

    async def _ensure_db(self) -> aiosqlite.Connection:
        if self._db is not None:
            return self._db

        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_CREATE_TABLE)
        return self._db

    async def get(self, key: str) -> str | None:
        """Get a setting value (decrypted if encrypted)."""
        db = await self._ensure_db()
        async with db.execute(
            "SELECT value, encrypted FROM settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            value, encrypted = row
            if encrypted:
                try:
                    return self._fernet.decrypt(value.encode()).decode()
                except Exception:
                    logger.warning("Failed to decrypt setting %s", key)
                    return None
            return value

    async def set(self, key: str, value: str, encrypted: bool = False) -> None:
        """Set a setting value (encrypts if encrypted=True)."""
        db = await self._ensure_db()
        store_value = value
        if encrypted:
            store_value = self._fernet.encrypt(value.encode()).decode()
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO settings (key, value, encrypted, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=?, encrypted=?, updated_at=?",
            (key, store_value, int(encrypted), now, store_value, int(encrypted), now),
        )
        await db.commit()

    async def get_all(self) -> dict[str, str]:
        """Get all settings (decrypted)."""
        db = await self._ensure_db()
        result: dict[str, str] = {}
        async with db.execute("SELECT key, value, encrypted FROM settings") as cursor:
            async for row in cursor:
                key, value, encrypted = row
                if encrypted:
                    try:
                        value = self._fernet.decrypt(value.encode()).decode()
                    except Exception:
                        logger.warning("Failed to decrypt setting %s", key)
                        continue
                result[key] = value
        return result

    async def has_key(self, key: str) -> bool:
        """Check if a setting key exists."""
        db = await self._ensure_db()
        async with db.execute(
            "SELECT 1 FROM settings WHERE key = ?", (key,)
        ) as cursor:
            return await cursor.fetchone() is not None

    async def delete(self, key: str) -> None:
        """Delete a setting."""
        db = await self._ensure_db()
        await db.execute("DELETE FROM settings WHERE key = ?", (key,))
        await db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
