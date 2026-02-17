"""SQLite-backed persistent state for notification services.

Stores known movie codes and notified IMAX titles so that
app restarts don't cause duplicate notifications.
Uses the same DB file as the healing strategy store (data/strategies.db).
"""

import logging
import os

import aiosqlite

logger = logging.getLogger(__name__)

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS notified_imax (
    title      TEXT PRIMARY KEY,
    notified_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS known_movies (
    movie_code  TEXT PRIMARY KEY,
    added_at    TEXT NOT NULL
);
"""


class NotificationStore:
    """Async SQLite store for notification state."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def _ensure_db(self) -> aiosqlite.Connection:
        if self._db is not None:
            return self._db

        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_CREATE_TABLES)
        return self._db

    # ---- IMAX ----

    async def is_imax_notified(self, title: str) -> bool:
        db = await self._ensure_db()
        async with db.execute(
            "SELECT 1 FROM notified_imax WHERE title = ?", (title,)
        ) as cursor:
            return await cursor.fetchone() is not None

    async def add_imax_title(self, title: str) -> None:
        db = await self._ensure_db()
        await db.execute(
            "INSERT OR IGNORE INTO notified_imax (title, notified_at) "
            "VALUES (?, datetime('now'))",
            (title,),
        )
        await db.commit()

    # ---- Known movies ----

    async def get_known_movie_codes(self) -> set[str]:
        db = await self._ensure_db()
        async with db.execute("SELECT movie_code FROM known_movies") as cursor:
            rows = await cursor.fetchall()
            return {row[0] for row in rows}

    async def add_movie_codes(self, codes: set[str]) -> None:
        if not codes:
            return
        db = await self._ensure_db()
        await db.executemany(
            "INSERT OR IGNORE INTO known_movies (movie_code, added_at) "
            "VALUES (?, datetime('now'))",
            [(code,) for code in codes],
        )
        await db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
