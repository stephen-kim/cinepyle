"""LLM API wrapper for extraction strategies and chat completion.

Supports multiple providers (Anthropic, OpenAI, Gemini).
Automatically selects whichever provider has an API key configured.
Priority: Anthropic > OpenAI > Gemini.
"""

import json
import logging
from dataclasses import dataclass

from cinepyle.healing.strategy import ExtractionTask

logger = logging.getLogger(__name__)

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


@dataclass
class LLMConfig:
    """Resolved LLM provider configuration."""

    provider: str  # "anthropic" | "openai" | "gemini"
    api_key: str


def resolve_llm_config(
    anthropic_key: str = "",
    openai_key: str = "",
    gemini_key: str = "",
) -> LLMConfig | None:
    """Pick the first available provider. Returns None if no key is set."""
    if anthropic_key:
        return LLMConfig(provider="anthropic", api_key=anthropic_key)
    if openai_key:
        return LLMConfig(provider="openai", api_key=openai_key)
    if gemini_key:
        return LLMConfig(provider="gemini", api_key=gemini_key)
    return None


def _build_user_message(
    task: ExtractionTask,
    trimmed_html: str,
    failed_js: str | None = None,
) -> str:
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
    return "\n".join(parts)


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences if the model added them."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = len(lines) - 1 if lines[-1].strip().startswith("```") else len(lines)
        text = "\n".join(lines[1:end]).strip()
    return text


async def _generate_anthropic(config: LLMConfig, user_message: str) -> str | None:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=config.api_key)
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


async def _generate_openai(config: LLMConfig, user_message: str) -> str | None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=config.api_key)
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=2000,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )
    return response.choices[0].message.content


async def _generate_gemini(config: LLMConfig, user_message: str) -> str | None:
    from google import genai

    client = genai.Client(api_key=config.api_key)
    response = await client.aio.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"{SYSTEM_PROMPT}\n\n{user_message}",
    )
    return response.text


_GENERATORS = {
    "anthropic": _generate_anthropic,
    "openai": _generate_openai,
    "gemini": _generate_gemini,
}


async def generate_extraction_strategy(
    config: LLMConfig,
    task: ExtractionTask,
    trimmed_html: str,
    failed_js: str | None = None,
) -> str | None:
    """Ask LLM to generate JS extraction code for the given task.

    Args:
        config: Resolved LLM provider configuration
        task: Description of what to extract
        trimmed_html: Reduced HTML of the page
        failed_js: Previously working JS that now fails (optional context)

    Returns:
        JavaScript code string, or None if generation fails.
    """
    user_message = _build_user_message(task, trimmed_html, failed_js)
    generator = _GENERATORS[config.provider]

    try:
        raw = await generator(config, user_message)
        if not raw:
            return None
        js_code = _strip_markdown_fences(raw)
        logger.info(
            "LLM (%s) generated strategy for %s (%d chars)",
            config.provider,
            task.task_id,
            len(js_code),
        )
        return js_code
    except Exception:
        logger.exception(
            "LLM (%s) strategy generation failed for %s",
            config.provider,
            task.task_id,
        )
        return None


# ------------------------------------------------------------------
# Generic chat completion with tool calling
# ------------------------------------------------------------------


async def _chat_anthropic(
    config: LLMConfig,
    system: str,
    messages: list[dict],
    tools: list[dict] | None,
    max_tokens: int,
) -> dict:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=config.api_key)

    kwargs: dict = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["parameters"],
            }
            for t in tools
        ]

    response = await client.messages.create(**kwargs)

    text = None
    tool_calls = []
    for block in response.content:
        if block.type == "text":
            text = block.text
        elif block.type == "tool_use":
            tool_calls.append(
                {"name": block.name, "arguments": block.input, "id": block.id}
            )

    return {"text": text, "tool_calls": tool_calls or None}


async def _chat_openai(
    config: LLMConfig,
    system: str,
    messages: list[dict],
    tools: list[dict] | None,
    max_tokens: int,
) -> dict:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=config.api_key)

    oai_messages = [{"role": "system", "content": system}]
    for m in messages:
        oai_messages.append({"role": m["role"], "content": m["content"]})

    kwargs: dict = {
        "model": "gpt-4o-mini",
        "max_tokens": max_tokens,
        "messages": oai_messages,
    }
    if tools:
        kwargs["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for t in tools
        ]

    response = await client.chat.completions.create(**kwargs)
    choice = response.choices[0]

    text = choice.message.content
    tool_calls = None
    if choice.message.tool_calls:
        tool_calls = [
            {
                "name": tc.function.name,
                "arguments": json.loads(tc.function.arguments),
                "id": tc.id,
            }
            for tc in choice.message.tool_calls
        ]

    return {"text": text, "tool_calls": tool_calls}


async def _chat_gemini(
    config: LLMConfig,
    system: str,
    messages: list[dict],
    tools: list[dict] | None,
    max_tokens: int,
) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.api_key)

    # Build contents
    contents = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(m["content"])]))

    # Build tool declarations
    gemini_tools = None
    if tools:
        declarations = []
        for t in tools:
            declarations.append(
                types.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters=t["parameters"],
                )
            )
        gemini_tools = [types.Tool(function_declarations=declarations)]

    config_obj = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=max_tokens,
        tools=gemini_tools,
    )

    response = await client.aio.models.generate_content(
        model="gemini-2.0-flash",
        contents=contents,
        config=config_obj,
    )

    text = None
    tool_calls = []
    if response.candidates and response.candidates[0].content:
        for part in response.candidates[0].content.parts:
            if part.text:
                text = part.text
            elif part.function_call:
                tool_calls.append(
                    {
                        "name": part.function_call.name,
                        "arguments": dict(part.function_call.args) if part.function_call.args else {},
                        "id": part.function_call.name,
                    }
                )

    return {"text": text, "tool_calls": tool_calls or None}


_CHAT_HANDLERS = {
    "anthropic": _chat_anthropic,
    "openai": _chat_openai,
    "gemini": _chat_gemini,
}


async def chat_completion(
    config: LLMConfig,
    system: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    max_tokens: int = 1024,
) -> dict:
    """Generic multi-turn chat completion with optional tool use.

    Args:
        config: Resolved LLM provider configuration.
        system: System prompt string.
        messages: List of {"role": "user"|"assistant", "content": str} dicts.
        tools: Optional list of tool definitions in canonical format:
               {"name": str, "description": str, "parameters": {JSON Schema}}
        max_tokens: Maximum tokens in response.

    Returns:
        {"text": str | None, "tool_calls": list[dict] | None}
        where each tool_call is {"name": str, "arguments": dict, "id": str}.
    """
    handler = _CHAT_HANDLERS[config.provider]

    try:
        result = await handler(config, system, messages, tools, max_tokens)
        logger.info(
            "Chat completion (%s): text=%s, tools=%d",
            config.provider,
            bool(result.get("text")),
            len(result.get("tool_calls") or []),
        )
        return result
    except Exception:
        logger.exception("Chat completion (%s) failed", config.provider)
        return {"text": None, "tool_calls": None}
