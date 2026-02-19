"""Watcha Pedia box office scraper via Playwright.

Navigates to pedia.watcha.com/ko-KR, scrolls to the bottom to trigger
lazy-loading of the box office section, then extracts movie rankings.
No authentication required.
"""

import logging

from playwright.async_api import Page

logger = logging.getLogger(__name__)

WATCHA_HOME_URL = "https://pedia.watcha.com/ko-KR"


async def fetch_watcha_box_office() -> list[dict]:
    """Scrape box office rankings from Watcha Pedia home page.

    Returns a list of dicts with keys: rank, name, code.
    - rank: string position (e.g., "1", "2")
    - name: movie title in Korean
    - code: Watcha content code (e.g., "mWXqYdA") or empty string

    Returns empty list on failure.
    """
    from cinepyle.browser.manager import BrowserManager

    mgr = BrowserManager.instance()
    ctx = await mgr.get_context("watcha_public")
    page = await ctx.new_page()

    try:
        return await _scrape_box_office(page)
    except Exception:
        logger.exception("Watcha box office scraping failed")
        return []
    finally:
        await page.close()


async def _scrape_box_office(page: Page) -> list[dict]:
    """Navigate, scroll to bottom, extract box office data."""
    await page.goto(WATCHA_HOME_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_load_state("networkidle", timeout=15_000)

    # Scroll down until "박스오피스" section appears
    await _scroll_to_bottom(page)

    # Wait for the section to fully render after scroll
    await page.wait_for_timeout(2000)

    # Extract box office data via JS evaluation
    movies: list[dict] = await page.evaluate("""() => {
        const results = [];

        // Find a heading containing "박스오피스"
        const headings = document.querySelectorAll(
            'h2, h3, h4, [class*="title"], [class*="heading"], [class*="header"]'
        );

        let boxOfficeSection = null;
        for (const h of headings) {
            if (h.textContent.includes('박스오피스')) {
                boxOfficeSection = h.closest(
                    'section, [class*="section"], [class*="collection"], '
                    + '[class*="rail"], [class*="carousel"], [class*="slider"]'
                ) || h.parentElement;
                break;
            }
        }

        if (!boxOfficeSection) {
            // Broader fallback: find any container with "박스오피스" text
            // that also has content links
            const allElements = document.querySelectorAll('*');
            for (const el of allElements) {
                const children = el.children;
                if (children.length > 2
                    && el.textContent.includes('박스오피스')
                    && el.querySelector('a[href*="/contents/"]')) {
                    boxOfficeSection = el;
                    break;
                }
            }
        }

        if (!boxOfficeSection) return results;

        // Extract movie items from content links
        const links = boxOfficeSection.querySelectorAll('a[href*="/contents/"]');
        let rank = 1;
        const seen = new Set();

        for (const link of links) {
            const href = link.getAttribute('href') || '';
            const codeMatch = href.match(/\\/contents\\/([^/?]+)/);
            const code = codeMatch ? codeMatch[1] : '';

            // Get movie name: try specific selectors first, then full text
            const nameEl = link.querySelector(
                '[class*="title"], [class*="name"], h3, h4'
            );
            let name = '';
            if (nameEl) {
                name = nameEl.textContent.trim();
            } else {
                // Use innerText to get visible text only (not hidden elements)
                const texts = link.innerText.split('\\n')
                    .map(t => t.trim())
                    .filter(t => t.length > 0);
                // Pick the longest text (likely the title)
                name = texts.reduce((a, b) => a.length >= b.length ? a : b, '');
            }

            // Clean up: remove leading rank numbers, whitespace
            name = name.replace(/^\\d+\\.?\\s*/, '').trim();

            if (name && !seen.has(name)) {
                seen.add(name);
                results.push({
                    rank: String(rank),
                    name: name,
                    code: code,
                });
                rank++;
            }
        }

        return results;
    }""")

    if not movies:
        logger.warning("No box office data found on Watcha Pedia page")
    else:
        logger.info("Watcha box office: scraped %d movies", len(movies))

    return movies


async def _scroll_to_bottom(page: Page, max_scrolls: int = 30) -> None:
    """Scroll the page incrementally to trigger lazy loading.

    Stops early once the "박스오피스" section is detected.
    """
    for _ in range(max_scrolls):
        previous_height = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(500)
        new_height = await page.evaluate("document.body.scrollHeight")

        # Check if box office section appeared
        found = await page.evaluate(
            "!!document.body.innerText.includes('박스오피스')"
        )
        if found:
            # One more scroll + wait to ensure the full section loads
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)
            break

        # No new content loaded — we've hit the bottom
        if new_height == previous_height:
            break
