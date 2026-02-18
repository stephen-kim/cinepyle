"""Movie news/article scrapers for daily digest.

Three sources:
  - Daum Entertainment Movie News
  - Cine21 (Korean film magazine)
  - Watcha Pedia Magazine
"""

import json
import logging
import re

import requests
from bs4 import BeautifulSoup

from cinepyle.digest import Article

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


# ---------------------------------------------------------------------------
# Google News RSS (Korean movie news)
# ---------------------------------------------------------------------------

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
GOOGLE_NEWS_PARAMS = {
    "q": "영화 개봉 OR 리뷰 OR 영화제 OR 시사회 OR 배우",
    "hl": "ko",
    "gl": "KR",
    "ceid": "KR:ko",
}


def scrape_google_news(max_articles: int = 20) -> list[Article]:
    """Scrape Korean movie news from Google News RSS."""
    resp = requests.get(
        GOOGLE_NEWS_RSS_URL,
        params=GOOGLE_NEWS_PARAMS,
        headers=_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "xml")

    articles: list[Article] = []

    for item in soup.find_all("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        source_el = item.find("source")

        if not title_el or not link_el:
            continue

        title = title_el.text.strip()
        url = link_el.text.strip()
        source_name = source_el.text.strip() if source_el else ""

        # Clean title: Google News often appends " - SourceName"
        if source_name and title.endswith(f" - {source_name}"):
            title = title[: -(len(source_name) + 3)].strip()

        if not title:
            continue

        articles.append(
            Article(
                title=title,
                url=url,
                source="google",
                summary=f"출처: {source_name}" if source_name else "",
                category="news",
            )
        )
        if len(articles) >= max_articles:
            break

    logger.info("Scraped %d articles from Google News", len(articles))
    return articles


# ---------------------------------------------------------------------------
# Cine21
# ---------------------------------------------------------------------------

CINE21_URL = "https://www.cine21.com"


def scrape_cine21(max_articles: int = 15) -> list[Article]:
    """Scrape articles from Cine21 main page."""
    resp = requests.get(CINE21_URL, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")

    articles: list[Article] = []
    seen_urls: set[str] = set()

    # Find all links to /news/view/?mag_id=...
    for link in soup.select("a[href*='/news/view/']"):
        href = link.get("href", "")
        if not href:
            continue
        # Build full URL
        if href.startswith("/"):
            url = f"{CINE21_URL}{href}"
        else:
            url = href

        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Extract title: prefer text, fall back to img alt
        title = link.get_text(strip=True)
        if not title:
            img = link.select_one("img")
            title = img.get("alt", "") if img else ""
        if not title or len(title) < 3:
            continue

        # Detect category from nearby text like [비평], [리뷰], [기획]
        category = ""
        full_text = link.get_text()
        cat_match = re.search(r"\[(비평|리뷰|기획|인터뷰|칼럼|뉴스|특집)\]", full_text)
        if cat_match:
            category = cat_match.group(1)
            title = title.replace(f"[{category}]", "").strip()

        articles.append(
            Article(
                title=title,
                url=url,
                source="cine21",
                category=category or "news",
            )
        )
        if len(articles) >= max_articles:
            break

    logger.info("Scraped %d articles from Cine21", len(articles))
    return articles


# ---------------------------------------------------------------------------
# Watcha Pedia Magazine
# ---------------------------------------------------------------------------

WATCHA_MAGAZINE_URL = "https://pedia.watcha.com/ko-KR/magazine"
WATCHA_HEADERS = {
    **_HEADERS,
    "x-watcha-client": "watcha-WebApp",
    "x-watcha-client-language": "ko",
    "x-watcha-client-region": "KR",
}


def scrape_watcha_magazine(max_articles: int = 15) -> list[Article]:
    """Scrape articles from Watcha Pedia Magazine."""
    resp = requests.get(WATCHA_MAGAZINE_URL, headers=WATCHA_HEADERS, timeout=15)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")

    articles: list[Article] = []
    seen_urls: set[str] = set()

    # Strategy 1: Try extracting from __INITIAL_DATA__ or __NEXT_DATA__
    for script in soup.select("script"):
        text = script.string or ""
        if "__INITIAL_DATA__" in text or "__NEXT_DATA__" in text:
            # Try to extract JSON
            match = re.search(
                r"(?:__INITIAL_DATA__|__NEXT_DATA__)\s*=\s*({.+?})(?:\s*;|\s*</)",
                text,
                re.DOTALL,
            )
            if match:
                try:
                    data = json.loads(match.group(1))
                    articles.extend(_parse_watcha_json(data, max_articles))
                except (json.JSONDecodeError, KeyError):
                    pass

    if articles:
        logger.info("Scraped %d articles from Watcha (JSON)", len(articles))
        return articles[:max_articles]

    # Strategy 2: Parse HTML links
    for link in soup.select("a[href*='/magazine/'], a[href*='/decks/']"):
        href = link.get("href", "")
        if not href or href == "/ko-KR/magazine":
            continue

        if href.startswith("/"):
            url = f"https://pedia.watcha.com{href}"
        else:
            url = href

        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Extract title from link text
        texts = [t.strip() for t in link.stripped_strings]
        if not texts:
            continue

        # Category is usually the first short text, title is the longest
        category = ""
        title = ""
        for t in texts:
            if t in ("아티클", "큐레이션", "왓피인터뷰", "콘텐츠소식"):
                category = t
            elif len(t) > len(title):
                title = t

        if not title or len(title) < 3:
            continue

        articles.append(
            Article(
                title=title,
                url=url,
                source="watcha",
                category=_watcha_category_map(category),
            )
        )
        if len(articles) >= max_articles:
            break

    logger.info("Scraped %d articles from Watcha (HTML)", len(articles))
    return articles


def _parse_watcha_json(data: dict, max_articles: int) -> list[Article]:
    """Try to extract magazine articles from Watcha's JSON data."""
    articles: list[Article] = []

    # Walk the JSON recursively looking for items with title + url-like fields
    def _walk(obj: object) -> None:
        if len(articles) >= max_articles:
            return
        if isinstance(obj, dict):
            # Check if this looks like a magazine item
            title = obj.get("title") or obj.get("name") or ""
            code = obj.get("code") or obj.get("id") or ""
            if title and code and isinstance(title, str) and len(title) > 3:
                url = f"https://pedia.watcha.com/ko-KR/magazine/{code}"
                cat_raw = obj.get("category_type") or obj.get("type") or ""
                articles.append(
                    Article(
                        title=title,
                        url=url,
                        source="watcha",
                        summary=obj.get("description", ""),
                        category=_watcha_category_map(str(cat_raw)),
                    )
                )
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(data)
    return articles


def _watcha_category_map(raw: str) -> str:
    """Map Watcha category labels to normalized names."""
    mapping = {
        "아티클": "article",
        "큐레이션": "curation",
        "왓피인터뷰": "interview",
        "콘텐츠소식": "news",
        "article": "article",
        "curation": "curation",
        "interview": "interview",
        "news": "news",
    }
    return mapping.get(raw, raw or "article")


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


def scrape_all(
    sources_enabled: dict[str, bool] | None = None,
) -> list[Article]:
    """Scrape all enabled sources and return combined article list."""
    if sources_enabled is None:
        sources_enabled = {"google": True, "cine21": True, "watcha": True}

    all_articles: list[Article] = []

    if sources_enabled.get("google"):
        try:
            all_articles.extend(scrape_google_news())
        except Exception:
            logger.exception("Failed to scrape Google News")

    if sources_enabled.get("cine21"):
        try:
            all_articles.extend(scrape_cine21())
        except Exception:
            logger.exception("Failed to scrape Cine21")

    if sources_enabled.get("watcha"):
        try:
            all_articles.extend(scrape_watcha_magazine())
        except Exception:
            logger.exception("Failed to scrape Watcha magazine")

    return all_articles
