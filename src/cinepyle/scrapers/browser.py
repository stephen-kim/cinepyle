"""Shared Playwright browser management.

Provides a singleton async browser instance for all scrapers and booking
sessions. The browser is lazily created on first use and shared across
the entire bot lifetime.

Usage:
    page = await get_page()       # Get a new page (tab)
    await page.goto(url)
    # ... use page ...
    await page.close()            # Close page when done

    await close_browser()         # Shutdown browser on bot exit
"""

import logging

from playwright.async_api import Browser, Page, async_playwright

logger = logging.getLogger(__name__)

_browser: Browser | None = None
_playwright_ctx = None


async def _ensure_browser() -> Browser:
    """Launch or return the shared headless Chromium browser."""
    global _browser, _playwright_ctx

    if _browser and _browser.is_connected():
        return _browser

    logger.info("Launching Playwright Chromium browser...")
    _playwright_ctx = await async_playwright().start()
    _browser = await _playwright_ctx.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    )
    logger.info("Browser launched (pid=%s)", _browser.contexts)
    return _browser


async def get_page() -> Page:
    """Create and return a new browser page (tab).

    The caller is responsible for closing the page when done:
        page = await get_page()
        try:
            await page.goto(url)
            ...
        finally:
            await page.close()
    """
    browser = await _ensure_browser()
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    )
    page = await context.new_page()
    return page


async def close_browser() -> None:
    """Shut down the shared browser. Called on bot exit."""
    global _browser, _playwright_ctx

    if _browser:
        try:
            await _browser.close()
            logger.info("Browser closed.")
        except Exception:
            logger.exception("Error closing browser")
        _browser = None

    if _playwright_ctx:
        try:
            await _playwright_ctx.stop()
        except Exception:
            logger.exception("Error stopping Playwright")
        _playwright_ctx = None
