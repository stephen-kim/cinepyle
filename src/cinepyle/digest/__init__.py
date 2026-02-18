"""Daily movie digest — data models."""

from dataclasses import dataclass, field


@dataclass
class Article:
    """A scraped article from any source."""

    title: str
    url: str
    source: str  # "daum" | "cine21" | "watcha"
    summary: str = ""
    category: str = ""  # "news", "review", "interview", "curation", etc.

    def to_llm_text(self) -> str:
        """Format for LLM input."""
        parts = [f"[{self.source}] {self.title}"]
        if self.category:
            parts.append(f"  분류: {self.category}")
        if self.summary:
            parts.append(f"  요약: {self.summary[:200]}")
        return "\n".join(parts)


@dataclass
class SelectedArticle:
    """An article selected by the LLM for the digest."""

    title: str
    url: str
    source: str
    summary: str  # LLM-generated one-line Korean summary


@dataclass
class DigestResult:
    """Complete digest output from LLM curation."""

    headline: str
    articles: list[SelectedArticle] = field(default_factory=list)
