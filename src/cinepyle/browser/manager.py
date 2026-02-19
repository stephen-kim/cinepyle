"""Playwright browser lifecycle manager.

Provides a lazy singleton that starts Chromium on first use and
keeps it alive for subsequent requests.  Supports separate browser
contexts for different cinema chain logins (cookie isolation).
"""

import asyncio
import logging
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

logger = logging.getLogger(__name__)

BROWSER_DATA_DIR = Path("data/browser")

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class BrowserManager:
    """Lazy singleton managing a shared Playwright browser instance.

    Usage::

        mgr = BrowserManager.instance()
        ctx = await mgr.get_context("cgv")
        page = await ctx.new_page()
        ...
        await page.close()
    """

    _instance: "BrowserManager | None" = None

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._contexts: dict[str, BrowserContext] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def instance(cls) -> "BrowserManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def _ensure_browser(self) -> Browser:
        async with self._lock:
            if self._browser is None:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                logger.info("Playwright browser launched")
            return self._browser

    async def get_context(self, name: str = "default") -> BrowserContext:
        """Get or create a named browser context.

        Each context has isolated cookies/storage, allowing
        simultaneous login sessions for different cinema chains.
        """
        if name not in self._contexts:
            browser = await self._ensure_browser()
            storage_dir = BROWSER_DATA_DIR / name
            storage_dir.mkdir(parents=True, exist_ok=True)
            storage_file = storage_dir / "state.json"

            kwargs: dict = {
                "user_agent": _UA,
                "locale": "ko-KR",
            }

            if storage_file.exists():
                kwargs["storage_state"] = str(storage_file)

            self._contexts[name] = await browser.new_context(**kwargs)

        return self._contexts[name]

    async def save_context(self, name: str) -> None:
        """Persist cookies/storage for a context."""
        if name in self._contexts:
            storage_dir = BROWSER_DATA_DIR / name
            storage_dir.mkdir(parents=True, exist_ok=True)
            await self._contexts[name].storage_state(
                path=str(storage_dir / "state.json")
            )

    async def shutdown(self) -> None:
        """Close all contexts and the browser.  Called at bot shutdown."""
        for name in list(self._contexts):
            try:
                await self.save_context(name)
                await self._contexts[name].close()
            except Exception:
                logger.debug("Error closing context %s", name)
        self._contexts.clear()

        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        logger.info("Playwright browser shut down")
