"""Self-healing extraction engine.

Orchestrates the three-tier fallback strategy:
1. Cached LLM strategy from SQLite
2. Hardcoded JS from source code
3. Live LLM generation via Claude API

Results are validated before caching. A cooldown prevents
excessive LLM calls when a site is persistently broken.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from playwright.async_api import Page

from cinepyle.healing.html_trimmer import trim_html
from cinepyle.healing.llm import LLMConfig, generate_extraction_strategy
from cinepyle.healing.store import StrategyStore
from cinepyle.healing.strategy import ExtractionStrategy, ExtractionTask

logger = logging.getLogger(__name__)

# Don't call LLM again for the same task within this window
LLM_COOLDOWN_SECONDS = 600  # 10 minutes


class HealingEngine:
    """Orchestrates self-healing extraction: cache → hardcoded → LLM."""

    def __init__(self, llm_config: LLMConfig | None, db_path: str = "data/strategies.db") -> None:
        self.llm_config = llm_config
        self.store = StrategyStore(db_path)
        self._llm_cooldowns: dict[str, datetime] = {}

    async def extract(
        self,
        page: Page,
        task: ExtractionTask,
        hardcoded_js: str | None = None,
    ) -> Any:
        """Try to extract data from a page, self-healing on failure.

        Args:
            page: Playwright page (already navigated to target URL)
            task: Describes what to extract
            hardcoded_js: Built-in JS code as fallback

        Returns:
            Extracted value, or None if all strategies fail.
        """
        # Step 1: Try cached strategy
        cached = await self.store.get_strategy(task.task_id)
        if cached:
            result = await self._execute_js(page, cached.js_code)
            if self._validate(result, task):
                await self.store.record_success(task.task_id)
                logger.debug("Cached strategy succeeded for %s", task.task_id)
                return result
            else:
                logger.warning(
                    "Cached strategy failed for %s (v%d)",
                    task.task_id,
                    cached.version,
                )
                await self.store.record_failure(task.task_id)

        # Step 2: Try hardcoded JS
        if hardcoded_js:
            result = await self._execute_js(page, hardcoded_js)
            if self._validate(result, task):
                logger.debug("Hardcoded strategy succeeded for %s", task.task_id)
                return result
            logger.warning("Hardcoded strategy failed for %s", task.task_id)

        # Step 3: Try LLM generation
        if not self.llm_config:
            logger.debug("No LLM configured, skipping for %s", task.task_id)
            return None

        if self._is_on_cooldown(task.task_id):
            logger.debug("LLM on cooldown for %s", task.task_id)
            return None

        raw_html = await page.content()
        trimmed = trim_html(raw_html)

        failed_js = cached.js_code if cached else hardcoded_js
        new_js = await generate_extraction_strategy(
            self.llm_config,
            task,
            trimmed,
            failed_js=failed_js,
        )
        if not new_js:
            self._set_cooldown(task.task_id)
            return None

        # Step 4: Execute and validate LLM strategy
        result = await self._execute_js(page, new_js)
        if self._validate(result, task):
            version = (cached.version + 1) if cached else 1
            strategy = ExtractionStrategy(
                task_id=task.task_id,
                js_code=new_js,
                version=version,
                created_at=datetime.now(timezone.utc).isoformat(),
                source="llm",
            )
            await self.store.save_strategy(strategy)
            logger.info(
                "LLM strategy cached for %s (v%d)", task.task_id, version
            )
            return result

        logger.error("LLM strategy failed validation for %s", task.task_id)
        self._set_cooldown(task.task_id)
        return None

    async def _execute_js(self, page: Page, js_code: str) -> Any:
        """Execute JS in page context, catching errors."""
        try:
            return await page.evaluate(js_code)
        except Exception:
            logger.debug("JS execution failed", exc_info=True)
            return None

    def _validate(self, result: Any, task: ExtractionTask) -> bool:
        """Check that the result matches expected type and constraints."""
        if result is None:
            return False

        if task.expected_type == "string":
            if not isinstance(result, str) or len(result.strip()) == 0:
                return False
            # Reject raw HTML
            if "<" in result and ">" in result:
                return False
            return True

        if task.expected_type == "float":
            try:
                val = float(result)
                return 0.0 < val <= 10.0
            except (ValueError, TypeError):
                return False

        if task.expected_type == "list[dict]":
            return isinstance(result, list) and len(result) > 0

        # Fallback: anything non-None is valid
        return True

    def _is_on_cooldown(self, task_id: str) -> bool:
        """Check if we recently failed LLM generation for this task."""
        if task_id not in self._llm_cooldowns:
            return False
        elapsed = (
            datetime.now(timezone.utc) - self._llm_cooldowns[task_id]
        ).total_seconds()
        return elapsed < LLM_COOLDOWN_SECONDS

    def _set_cooldown(self, task_id: str) -> None:
        """Mark that LLM failed for this task, starting cooldown."""
        self._llm_cooldowns[task_id] = datetime.now(timezone.utc)

    async def close(self) -> None:
        """Close the strategy store."""
        await self.store.close()
