"""LLM-driven natural language booking handler.

Replaces the rigid /book ConversationHandler with an LLM agent that
understands free-form Korean text. Falls back to the legacy
ConversationHandler when no LLM API key is configured.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from cinepyle.config import ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY
from cinepyle.healing.llm import resolve_llm_config
from cinepyle.nlp.agent import BookingAgent
from cinepyle.nlp.state import BookingPhase

logger = logging.getLogger(__name__)

# Keywords that suggest booking intent (used when no active session)
_BOOKING_KEYWORDS = [
    "예매",
    "예약",
    "booking",
    "book",
    "표 사",
    "표사",
    "티켓",
    "cgv",
    "CGV",
    "롯데시네마",
    "메가박스",
    "씨네",
    "영화 보",
    "영화보",
    "볼만한",
    "영화관",
]


def _is_booking_intent(text: str) -> bool:
    """Quick keyword check to detect booking intent without LLM."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in _BOOKING_KEYWORDS)


def _get_or_create_agent(
    context: ContextTypes.DEFAULT_TYPE,
) -> BookingAgent | None:
    """Get existing agent from user_data or create a new one.

    Returns None if no LLM API key is configured.
    """
    agent = context.user_data.get("booking_agent")
    if agent is not None:
        return agent

    config = resolve_llm_config(ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY)
    if not config:
        return None

    agent = BookingAgent(config)
    context.user_data["booking_agent"] = agent
    return agent


# ------------------------------------------------------------------
# Handler: /book command
# ------------------------------------------------------------------


async def book_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point: /book command or /book with natural language."""
    agent = _get_or_create_agent(context)

    if not agent:
        # Fallback to legacy ConversationHandler
        try:
            from cinepyle.bot.booking_legacy import build_booking_handler

            logger.warning("No LLM configured — /book requires LLM API key")
            await update.message.reply_text(
                "LLM API 키가 설정되지 않아 자연어 예매를 사용할 수 없습니다.\n"
                "ANTHROPIC_API_KEY, OPENAI_API_KEY, 또는 GEMINI_API_KEY를 설정해주세요."
            )
        except Exception:
            await update.message.reply_text("예매 기능을 사용할 수 없습니다.")
        return

    # If there's text after /book, use it as the initial query
    text = update.message.text or ""
    user_input = text.replace("/book", "").strip()
    if not user_input:
        user_input = "영화 예매하고 싶어요"

    await agent.handle_message(user_input, update, context)


# ------------------------------------------------------------------
# Handler: free-text messages
# ------------------------------------------------------------------


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch-all TEXT handler for active booking sessions and new intents."""
    text = update.message.text or ""
    agent: BookingAgent | None = context.user_data.get("booking_agent")

    # Case 1: Active booking session in deterministic phase
    if agent and agent.state.phase in (
        BookingPhase.AWAITING_CAPTCHA,
        BookingPhase.SELECTING_SEATS,
        BookingPhase.AWAITING_AUTH,
    ):
        await agent.handle_deterministic(text, update, context)
        return

    # Case 2: Active booking session in LLM phase
    if agent and agent.state.phase in (
        BookingPhase.GATHERING_INFO,
        BookingPhase.CHOOSING_PAYMENT,
        BookingPhase.LOGGING_IN,
    ):
        await agent.handle_message(text, update, context)
        return

    # Case 3: No active session — check if text looks like a booking intent
    if _is_booking_intent(text):
        agent = _get_or_create_agent(context)
        if agent:
            await agent.handle_message(text, update, context)
            return

    # Case 4: Not a booking intent and no active session — ignore
    # (Let other handlers or the default handler deal with it)


# ------------------------------------------------------------------
# Handler: payment callback buttons
# ------------------------------------------------------------------


async def callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle inline button callbacks (payment method selection)."""
    query = update.callback_query
    if not query or not query.data:
        return

    if not query.data.startswith("nlpay:"):
        return

    await query.answer()

    agent: BookingAgent | None = context.user_data.get("booking_agent")
    if not agent:
        await query.message.reply_text("예매 세션이 만료되었습니다.")
        return

    method = query.data.split(":", 1)[1]
    await agent.handle_payment(method, update, context)


# ------------------------------------------------------------------
# Build handlers for registration in main.py
# ------------------------------------------------------------------


def build_booking_handlers() -> list:
    """Return the list of handlers for NLP booking.

    Returns handlers in the order they should be registered:
    1. /book command
    2. Payment callback
    3. Text catch-all (should be registered LAST)
    """
    return [
        CommandHandler("book", book_command),
        CallbackQueryHandler(callback_handler, pattern=r"^nlpay:"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler),
    ]
