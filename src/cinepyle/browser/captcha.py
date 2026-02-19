"""CAPTCHA solver using LLM vision APIs.

Captures a screenshot of the CAPTCHA element, sends it to an LLM
with vision capabilities, and returns the recognized text.

Supports OpenAI (gpt-4o-mini), Anthropic (claude-3-5-haiku), and
Google Gemini (gemini-2.0-flash) — picks whichever is configured
via ``config.resolve_llm()``.
"""

from __future__ import annotations

import base64
import logging

from playwright.async_api import Page

logger = logging.getLogger(__name__)

# Vision-capable models per provider
_VISION_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "google": "gemini-2.0-flash",
}

_PROMPT = (
    "이미지에 보이는 CAPTCHA 문자를 정확히 읽어줘. "
    "영문 대소문자와 숫자만 포함되어 있어. "
    "다른 설명 없이 CAPTCHA 텍스트만 출력해."
)


async def solve_captcha(page: Page, selector: str) -> str:
    """Screenshot the CAPTCHA element and OCR it via LLM vision.

    Args:
        page: Playwright page containing the CAPTCHA.
        selector: CSS selector for the CAPTCHA image or wrapper element.

    Returns:
        Recognized text (stripped), or empty string on failure.
    """
    from cinepyle.config import resolve_llm

    provider, api_key, model = resolve_llm()
    if not provider or not api_key:
        logger.warning("No LLM provider configured — cannot solve CAPTCHA")
        return ""

    # Capture the CAPTCHA element as PNG
    try:
        el = page.locator(selector).first
        png_bytes = await el.screenshot(type="png")
    except Exception:
        logger.exception("Failed to screenshot CAPTCHA element '%s'", selector)
        return ""

    if not png_bytes:
        return ""

    b64 = base64.b64encode(png_bytes).decode()
    logger.info(
        "CAPTCHA screenshot captured (%d bytes), sending to %s",
        len(png_bytes),
        provider,
    )

    try:
        text = _call_vision(provider, api_key, model, b64)
        # Strip whitespace and any surrounding quotes
        text = text.strip().strip("'\"").strip()
        logger.info("CAPTCHA OCR result: %r", text)
        return text
    except Exception:
        logger.exception("CAPTCHA OCR failed (%s)", provider)
        return ""


def _call_vision(
    provider: str, api_key: str, model: str, image_b64: str
) -> str:
    """Send base64 PNG to an LLM vision endpoint and return the text."""

    if provider == "openai":
        import openai

        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model or _VISION_MODELS["openai"],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_b64}",
                            },
                        },
                    ],
                }
            ],
            max_tokens=32,
            temperature=0,
        )
        return resp.choices[0].message.content or ""

    elif provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model or _VISION_MODELS["anthropic"],
            max_tokens=32,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        )
        return resp.content[0].text if resp.content else ""

    elif provider == "google":
        from google.genai import types

        client = __import__("google.genai", fromlist=["genai"]).Client(
            api_key=api_key
        )
        config = types.GenerateContentConfig(
            max_output_tokens=32,
            temperature=0,
        )
        resp = client.models.generate_content(
            model=model or _VISION_MODELS["google"],
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(
                            data=base64.b64decode(image_b64),
                            mime_type="image/png",
                        ),
                        types.Part.from_text(text=_PROMPT),
                    ],
                )
            ],
            config=config,
        )
        return resp.text or ""

    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
