"""Scheduled job for daily movie digest."""

import logging

from telegram.ext import ContextTypes

from cinepyle.digest.formatter import format_digest_message, format_fallback_digest
from cinepyle.digest.llm import get_provider
from cinepyle.digest.scrapers import scrape_all
from cinepyle.digest.settings import DigestSettings

logger = logging.getLogger(__name__)


async def send_digest_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: scrape sources, curate with LLM, send digest."""
    chat_id = context.job.data
    settings = DigestSettings.load()

    if not settings.schedule_enabled:
        return

    # Step 1: Scrape enabled sources
    all_articles = scrape_all(settings.sources_enabled)

    if not all_articles:
        logger.warning("No articles scraped from any source")
        return

    # Step 2: LLM curation (with fallback)
    messages: list[str]

    if settings.llm_api_key:
        try:
            provider = get_provider(settings.llm_provider, settings.llm_api_key)
            digest = provider.select_and_summarize(all_articles, settings.preferences)
            messages = format_digest_message(digest)
        except Exception:
            logger.exception("LLM curation failed, using fallback")
            messages = format_fallback_digest(all_articles)
    else:
        logger.info("No LLM API key configured, using fallback digest")
        messages = format_fallback_digest(all_articles)

    # Step 3: Send via Telegram
    for msg in messages:
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    logger.info(
        "Daily digest sent: %d message(s), %d articles scraped",
        len(messages),
        len(all_articles),
    )
