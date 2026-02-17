"""Claude API wrapper for generating extraction strategies.

Sends trimmed HTML and task description to Claude, which generates
JavaScript code for Playwright's page.evaluate(). The JS code
extracts the desired data from the page DOM.
"""

import logging

from anthropic import AsyncAnthropic

from cinepyle.healing.strategy import ExtractionTask

logger = logging.getLogger(__name__)

_client: AsyncAnthropic | None = None

SYSTEM_PROMPT = """\
You are an expert web scraper. Given an HTML page and a description \
of what data to extract, you write JavaScript code that extracts the \
data when executed via Playwright's page.evaluate().

Rules:
1. Return ONLY the JavaScript code. No markdown fences, no explanation.
2. The code must be a single IIFE: (() => { ... })()
3. Return null if the data cannot be found.
4. Do not use fetch() or any async operations.
5. The code runs in browser context with access to document and window.
6. Be resilient: use multiple fallback strategies within the code.
7. Prefer semantic selectors (aria-label, role, text content, tag names) \
over class names, since class names change frequently on Korean sites.
8. When searching text content, consider both Korean (한국어) and English."""


def _get_client(api_key: str) -> AsyncAnthropic:
    """Get or create the Anthropic client singleton."""
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=api_key)
    return _client


async def generate_extraction_strategy(
    api_key: str,
    task: ExtractionTask,
    trimmed_html: str,
    failed_js: str | None = None,
) -> str | None:
    """Ask Claude to generate JS extraction code for the given task.

    Args:
        api_key: Anthropic API key
        task: Description of what to extract
        trimmed_html: Reduced HTML of the page
        failed_js: Previously working JS that now fails (optional context)

    Returns:
        JavaScript code string, or None if generation fails.
    """
    client = _get_client(api_key)

    parts = [
        f"Task: {task.description}",
        f"URL: {task.url}",
        f"Expected result type: {task.expected_type}",
        f"Example valid result: {task.example_result}",
        f"Validation: {task.validation_hint}",
    ]

    if failed_js:
        parts.append(
            "\nThe following JS code USED TO WORK but no longer does. "
            "The site likely changed its structure. Generate a new approach:\n"
            f"```\n{failed_js}\n```"
        )

    parts.append(f"\nHere is the current HTML of the page:\n\n{trimmed_html}")

    user_message = "\n".join(parts)

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        js_code = response.content[0].text.strip()

        # Strip markdown fences if the model added them
        if js_code.startswith("```"):
            lines = js_code.split("\n")
            end = len(lines) - 1 if lines[-1].strip().startswith("```") else len(lines)
            js_code = "\n".join(lines[1:end]).strip()

        logger.info(
            "LLM generated strategy for %s (%d chars)",
            task.task_id,
            len(js_code),
        )
        return js_code

    except Exception:
        logger.exception("LLM strategy generation failed for %s", task.task_id)
        return None
