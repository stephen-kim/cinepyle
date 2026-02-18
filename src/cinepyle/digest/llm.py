"""LLM integration for article curation.

Supports OpenAI, Anthropic, and Google Gemini. Each provider receives
the scraped article list and user preferences, then returns a curated
digest with selected articles and one-line Korean summaries.
"""

import json
import logging
from abc import ABC, abstractmethod

from cinepyle.digest import Article, DigestResult, SelectedArticle

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
당신은 한국 영화 뉴스 큐레이터입니다.
아래 기사 목록에서 영화 팬이 가장 흥미롭게 읽을 만한 5~8개를 선별해주세요.
품질, 독창성, 관련성을 고려하여 고르세요."""

USER_PROMPT_TEMPLATE = """\
{preferences_section}
기사 목록:
{article_list}

아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "headline": "오늘의 다이제스트를 대표하는 창의적인 한국어 헤드라인",
  "articles": [
    {{
      "index": 기사번호,
      "summary": "한국어 한줄 요약"
    }}
  ]
}}"""


def _build_prompt(articles: list[Article], preferences: str) -> str:
    """Build the user prompt with article list and preferences."""
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(f"{i}. {a.to_llm_text()}")

    preferences_section = ""
    if preferences:
        preferences_section = f"사용자 취향: {preferences}\n\n"

    return USER_PROMPT_TEMPLATE.format(
        preferences_section=preferences_section,
        article_list="\n".join(lines),
    )


def _parse_llm_response(
    raw: str, articles: list[Article]
) -> DigestResult:
    """Parse LLM JSON response into DigestResult."""
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    data = json.loads(text)
    headline = data.get("headline", "오늘의 영화 소식")

    selected: list[SelectedArticle] = []
    for item in data.get("articles", []):
        idx = item.get("index", 0) - 1  # 1-indexed → 0-indexed
        if 0 <= idx < len(articles):
            a = articles[idx]
            selected.append(
                SelectedArticle(
                    title=a.title,
                    url=a.url,
                    source=a.source,
                    summary=item.get("summary", a.summary),
                )
            )

    return DigestResult(headline=headline, articles=selected)


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract LLM provider for article curation."""

    @abstractmethod
    def select_and_summarize(
        self, articles: list[Article], preferences: str
    ) -> DigestResult:
        ...


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        import openai

        self.client = openai.OpenAI(api_key=api_key)
        self.model = model

    def select_and_summarize(
        self, articles: list[Article], preferences: str
    ) -> DigestResult:
        prompt = _build_prompt(articles, preferences)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        raw = response.choices[0].message.content or "{}"
        return _parse_llm_response(raw, articles)


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


class AnthropicProvider(LLMProvider):
    def __init__(
        self, api_key: str, model: str = "claude-3-5-haiku-latest"
    ) -> None:
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def select_and_summarize(
        self, articles: list[Article], preferences: str
    ) -> DigestResult:
        prompt = _build_prompt(articles, preferences)
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        return _parse_llm_response(raw, articles)


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------


class GoogleProvider(LLMProvider):
    def __init__(
        self, api_key: str, model: str = "gemini-2.0-flash"
    ) -> None:
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def select_and_summarize(
        self, articles: list[Article], preferences: str
    ) -> DigestResult:
        prompt = f"{SYSTEM_PROMPT}\n\n{_build_prompt(articles, preferences)}"
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        raw = response.text or "{}"
        return _parse_llm_response(raw, articles)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
}


def get_provider(provider_name: str, api_key: str) -> LLMProvider:
    """Create an LLM provider by name."""
    cls = _PROVIDERS.get(provider_name)
    if cls is None:
        raise ValueError(
            f"Unknown LLM provider: {provider_name!r}. "
            f"Choose from: {', '.join(_PROVIDERS)}"
        )
    return cls(api_key)
