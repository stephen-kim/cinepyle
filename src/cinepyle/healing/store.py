"""SQLite-backed strategy cache for self-healing extraction.

Stores successful extraction strategies so the LLM doesn't need
to be called on every scrape. Strategies are invalidated after
repeated failures, triggering LLM regeneration.
"""

import logging
import os
from datetime import datetime, timezone

import aiosqlite

from cinepyle.healing.strategy import ExtractionStrategy

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS strategies (
    task_id       TEXT PRIMARY KEY,
    js_code       TEXT NOT NULL,
    version       INTEGER NOT NULL DEFAULT 1,
    source        TEXT NOT NULL DEFAULT 'llm',
    created_at    TEXT NOT NULL,
    last_used     TEXT,
    success_count INTEGER NOT NULL DEFAULT 0,
    fail_count    INTEGER NOT NULL DEFAULT 0
)
"""

# After this many consecutive failures, delete the cached strategy
# so the LLM is called again on the next attempt.
MAX_FAILURES = 3


class StrategyStore:
    """Async SQLite store for extraction strategies."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def _ensure_db(self) -> aiosqlite.Connection:
        """Lazily open the database and create the table."""
        if self._db is not None:
            return self._db

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(_CREATE_TABLE)
        await self._db.commit()
        return self._db

    async def get_strategy(self, task_id: str) -> ExtractionStrategy | None:
        """Return the cached strategy for a task, or None."""
        db = await self._ensure_db()
        async with db.execute(
            "SELECT * FROM strategies WHERE task_id = ?", (task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return ExtractionStrategy(
                task_id=row["task_id"],
                js_code=row["js_code"],
                version=row["version"],
                created_at=row["created_at"],
                source=row["source"],
            )

    async def save_strategy(self, strategy: ExtractionStrategy) -> None:
        """Insert or replace a strategy, resetting failure count."""
        db = await self._ensure_db()
        await db.execute(
            """
            INSERT INTO strategies (task_id, js_code, version, source, created_at,
                                    last_used, success_count, fail_count)
            VALUES (?, ?, ?, ?, ?, ?, 0, 0)
            ON CONFLICT(task_id) DO UPDATE SET
                js_code = excluded.js_code,
                version = excluded.version,
                source = excluded.source,
                created_at = excluded.created_at,
                fail_count = 0
            """,
            (
                strategy.task_id,
                strategy.js_code,
                strategy.version,
                strategy.source,
                strategy.created_at,
            ),
        )
        await db.commit()
        logger.info(
            "Strategy saved: %s v%d (%s)",
            strategy.task_id,
            strategy.version,
            strategy.source,
        )

    async def record_success(self, task_id: str) -> None:
        """Record a successful extraction, resetting fail count."""
        db = await self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """
            UPDATE strategies
            SET success_count = success_count + 1,
                fail_count = 0,
                last_used = ?
            WHERE task_id = ?
            """,
            (now, task_id),
        )
        await db.commit()

    async def record_failure(self, task_id: str) -> None:
        """Record a failed extraction. Deletes strategy after MAX_FAILURES."""
        db = await self._ensure_db()
        await db.execute(
            "UPDATE strategies SET fail_count = fail_count + 1 WHERE task_id = ?",
            (task_id,),
        )
        await db.commit()

        # Check if we should invalidate
        async with db.execute(
            "SELECT fail_count FROM strategies WHERE task_id = ?", (task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row["fail_count"] >= MAX_FAILURES:
                await db.execute(
                    "DELETE FROM strategies WHERE task_id = ?", (task_id,)
                )
                await db.commit()
                logger.warning(
                    "Strategy invalidated after %d failures: %s",
                    MAX_FAILURES,
                    task_id,
                )

    async def close(self) -> None:
        """Close the database connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None
