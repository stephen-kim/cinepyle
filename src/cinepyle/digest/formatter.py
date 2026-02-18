"""Telegram message formatting for the daily digest."""

from html import escape

from cinepyle.digest import DigestResult, SelectedArticle

# Telegram HTML message limit
_MAX_MESSAGE_LEN = 4096

_SOURCE_EMOJI = {
    "google": "📰",
    "cine21": "🎬",
    "watcha": "🍿",
}

_SOURCE_LABEL = {
    "google": "뉴스",
    "cine21": "Cine21",
    "watcha": "Watcha",
}


def format_digest_message(digest: DigestResult) -> list[str]:
    """Format a DigestResult into one or more Telegram HTML messages.

    Returns a list of message strings (usually 1, but split if too long).
    """
    lines: list[str] = []
    lines.append(f"<b>📰 {escape(digest.headline)}</b>")
    lines.append("")

    for i, article in enumerate(digest.articles, 1):
        emoji = _SOURCE_EMOJI.get(article.source, "📄")
        label = _SOURCE_LABEL.get(article.source, article.source)
        lines.append(
            f"<b>{i}. {emoji} {escape(article.title)}</b>"
        )
        if article.summary:
            lines.append(f"    {escape(article.summary)}")
        lines.append(
            f'    <a href="{escape(article.url)}">{label}에서 읽기</a>'
        )
        lines.append("")

    full_text = "\n".join(lines).rstrip()

    # Split into multiple messages if too long
    if len(full_text) <= _MAX_MESSAGE_LEN:
        return [full_text]

    return _split_messages(digest)


def _split_messages(digest: DigestResult) -> list[str]:
    """Split a long digest into multiple messages, breaking at article boundaries."""
    messages: list[str] = []
    current_lines: list[str] = []
    current_lines.append(f"<b>📰 {escape(digest.headline)}</b>")
    current_lines.append("")

    for i, article in enumerate(digest.articles, 1):
        article_block = _format_single_article(i, article)
        candidate = "\n".join(current_lines) + "\n" + article_block

        if len(candidate) > _MAX_MESSAGE_LEN and current_lines:
            # Flush current
            messages.append("\n".join(current_lines).rstrip())
            current_lines = []

        current_lines.append(article_block)

    if current_lines:
        messages.append("\n".join(current_lines).rstrip())

    return messages


def _format_single_article(index: int, article: SelectedArticle) -> str:
    """Format one article block."""
    emoji = _SOURCE_EMOJI.get(article.source, "📄")
    label = _SOURCE_LABEL.get(article.source, article.source)
    lines = [
        f"<b>{index}. {emoji} {escape(article.title)}</b>",
    ]
    if article.summary:
        lines.append(f"    {escape(article.summary)}")
    lines.append(f'    <a href="{escape(article.url)}">{label}에서 읽기</a>')
    lines.append("")
    return "\n".join(lines)


def format_fallback_digest(articles: list) -> list[str]:
    """Format a simple digest without LLM curation (fallback)."""
    from cinepyle.digest import Article

    lines: list[str] = []
    lines.append("<b>📰 오늘의 영화 소식</b>")
    lines.append("")

    for i, a in enumerate(articles[:8], 1):
        if not isinstance(a, Article):
            continue
        emoji = _SOURCE_EMOJI.get(a.source, "📄")
        label = _SOURCE_LABEL.get(a.source, a.source)
        lines.append(f"<b>{i}. {emoji} {escape(a.title)}</b>")
        if a.summary:
            lines.append(f"    {escape(a.summary[:100])}")
        lines.append(f'    <a href="{escape(a.url)}">{label}에서 읽기</a>')
        lines.append("")

    text = "\n".join(lines).rstrip()
    if len(text) <= _MAX_MESSAGE_LEN:
        return [text]
    # Truncate if still too long
    return [text[:_MAX_MESSAGE_LEN]]
