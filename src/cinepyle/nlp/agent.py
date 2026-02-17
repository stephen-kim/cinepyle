"""LLM-powered booking agent for conversational movie ticket booking."""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from cinepyle.booking.base import BookingSession
from cinepyle.config import (
    CGV_ID,
    CGV_PASSWORD,
    CINEQ_ID,
    CINEQ_PASSWORD,
    LOTTECINEMA_ID,
    LOTTECINEMA_PASSWORD,
    MEGABOX_ID,
    MEGABOX_PASSWORD,
)
from cinepyle.healing.llm import LLMConfig, chat_completion
from cinepyle.navigation import format_directions_message
from cinepyle.nlp.prompts import BOOKING_SYSTEM_PROMPT, BOOKING_TOOLS
from cinepyle.nlp.state import BookingPhase, BookingState
from cinepyle.nlp.tools import execute_tool
from cinepyle.scrapers.browser import get_page

logger = logging.getLogger(__name__)

# Chain credentials fallback (from .env)
_CHAIN_CREDS_FALLBACK: dict[str, tuple[str, str]] = {
    "cgv": (CGV_ID, CGV_PASSWORD),
    "lotte": (LOTTECINEMA_ID, LOTTECINEMA_PASSWORD),
    "megabox": (MEGABOX_ID, MEGABOX_PASSWORD),
    "cineq": (CINEQ_ID, CINEQ_PASSWORD),
}


def _get_chain_creds(chain_key: str) -> tuple[str, str]:
    """Get chain credentials from SettingsManager, falling back to .env."""
    try:
        from cinepyle.dashboard.settings_manager import SettingsManager
        mgr = SettingsManager.get_instance()
        uid = mgr.get(f"credential:{chain_key}_id") or _CHAIN_CREDS_FALLBACK.get(chain_key, ("", ""))[0]
        pw = mgr.get(f"credential:{chain_key}_password") or _CHAIN_CREDS_FALLBACK.get(chain_key, ("", ""))[1]
        return (uid, pw)
    except (RuntimeError, ImportError):
        return _CHAIN_CREDS_FALLBACK.get(chain_key, ("", ""))

# Maximum tool-call rounds per user message
MAX_TOOL_ROUNDS = 5

# Session inactivity timeout (seconds)
SESSION_TIMEOUT = 300


async def _create_session(chain_key: str) -> BookingSession:
    """Create the appropriate BookingSession for a chain."""
    page = await get_page()
    uid, pw = _get_chain_creds(chain_key)

    if chain_key == "cgv":
        from cinepyle.booking.cgv import CGVBookingSession

        return CGVBookingSession(page, uid, pw)
    elif chain_key == "lotte":
        from cinepyle.booking.lotte import LotteBookingSession

        return LotteBookingSession(page, uid, pw)
    elif chain_key == "megabox":
        from cinepyle.booking.megabox import MegaBoxBookingSession

        return MegaBoxBookingSession(page, uid, pw)
    elif chain_key == "cineq":
        from cinepyle.booking.cineq import CineQBookingSession

        return CineQBookingSession(page, uid, pw)
    else:
        raise ValueError(f"Unknown chain: {chain_key}")


class BookingAgent:
    """LLM-powered booking agent for a single user conversation."""

    def __init__(self, llm_config: LLMConfig) -> None:
        self.llm_config = llm_config
        self.state = BookingState()

    # ------------------------------------------------------------------
    # Main entry: process a user message
    # ------------------------------------------------------------------

    async def handle_message(
        self,
        user_text: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Process a user message through the LLM agent loop."""
        # Set phase if this is the first message
        if self.state.phase == BookingPhase.IDLE:
            self.state.phase = BookingPhase.GATHERING_INFO

        # Add user message to conversation history
        self.state.add_message("user", user_text)

        # Build system prompt with current state
        now = datetime.now()
        _DAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]
        today_str = (
            f"{now.strftime('%Y년 %m월 %d일')} "
            f"({_DAYS_KO[now.weekday()]}요일)"
        )
        # Build preferred theaters context
        preferred_theaters_text = "등록된 선호 영화관이 없습니다."
        try:
            from cinepyle.dashboard.settings_manager import SettingsManager
            mgr = SettingsManager.get_instance()
            prefs = mgr.get_preferred_theaters()
            if prefs:
                _chain_display = {"cgv": "CGV", "lotte": "롯데시네마", "megabox": "메가박스", "cineq": "씨네Q"}
                lines = []
                for t in prefs:
                    chain_label = _chain_display.get(t["chain_key"], t["chain_key"])
                    lines.append(
                        f"- {t['name']} ({chain_label}) "
                        f"[chain_key: {t['chain_key']}, ID: {t['theater_code']}, "
                        f"RegionCode: {t.get('region_code', '')}]"
                    )
                preferred_theaters_text = "\n".join(lines)
        except (RuntimeError, ImportError):
            pass

        system = BOOKING_SYSTEM_PROMPT.format(
            state_summary=self.state.summary_for_llm(),
            today=today_str,
            preferred_theaters=preferred_theaters_text,
        )

        # Agent loop: LLM may emit multiple sequential tool calls
        for _ in range(MAX_TOOL_ROUNDS):
            result = await chat_completion(
                config=self.llm_config,
                system=system,
                messages=self.state.messages,
                tools=BOOKING_TOOLS,
                max_tokens=1024,
            )

            # LLM call failed
            if result["text"] is None and result["tool_calls"] is None:
                await self._send_text(
                    update,
                    "죄송합니다, 일시적인 오류가 발생했습니다. 다시 말씀해주세요.",
                )
                return

            # Case 1: LLM responded with text only (no tool call)
            if result["text"] and not result["tool_calls"]:
                await self._send_text(update, result["text"])
                self.state.add_message("assistant", result["text"])
                return

            # Case 2: LLM emitted tool calls
            if result["tool_calls"]:
                for tc in result["tool_calls"]:
                    tool_result = await execute_tool(
                        tc["name"], tc["arguments"], self.state
                    )

                    # Special sentinel: start the deterministic booking flow
                    if tool_result == "BOOKING_START":
                        await self._run_booking_flow(update, context)
                        return

                    # Cancel
                    if tool_result == "CANCELLED":
                        await self._cancel(update, context)
                        return

                    # If tool is respond_to_user, send message and return
                    if tc["name"] == "respond_to_user":
                        await self._send_text(update, tool_result)
                        self.state.add_message("assistant", tool_result)
                        return

                    # Otherwise, feed tool result back as context
                    self.state.add_message(
                        "assistant",
                        f"[{tc['name']} 결과]\n{tool_result}",
                    )
                continue

            # No text and no tool calls — break
            break

        # If we exit the loop without responding, send a fallback
        await self._send_text(
            update,
            "무엇을 도와드릴까요? 영화관, 영화, 시간 등을 말씀해주세요.",
        )

    # ------------------------------------------------------------------
    # Deterministic phase handler (no LLM)
    # ------------------------------------------------------------------

    async def handle_deterministic(
        self,
        text: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle responses in deterministic phases (CAPTCHA, seats, auth)."""
        phase = self.state.phase

        # Check for cancel keywords
        if text.strip().lower() in ("취소", "cancel", "/cancel"):
            await self._cancel(update, context)
            return

        if phase == BookingPhase.AWAITING_CAPTCHA:
            await self._handle_captcha(text, update, context)
        elif phase == BookingPhase.SELECTING_SEATS:
            await self._handle_seat_input(text, update, context)
        elif phase == BookingPhase.AWAITING_AUTH:
            await self._handle_auth_code(text, update, context)
        else:
            # Not in a deterministic phase — route through LLM
            await self.handle_message(text, update, context)

    # ------------------------------------------------------------------
    # Deterministic booking flow
    # ------------------------------------------------------------------

    async def _run_booking_flow(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Start the deterministic booking: login → navigate → seat map."""
        self.state.phase = BookingPhase.LOGGING_IN
        await self._send_text(update, "🔐 로그인 중...")

        try:
            session = await _create_session(self.state.chain)
        except Exception:
            logger.exception("Failed to create booking session")
            await self._send_text(update, "예매 세션 생성에 실패했습니다.")
            self.state.phase = BookingPhase.GATHERING_INFO
            return

        context.user_data["booking_session"] = session
        self.state.session_active = True

        try:
            result = await session.login()
        except Exception:
            logger.exception("Login failed for %s", self.state.chain)
            await self._send_text(update, "로그인에 실패했습니다.")
            await self._cleanup_session(context)
            return

        if isinstance(result, bytes):
            # CAPTCHA — send image and wait for answer
            self.state.phase = BookingPhase.AWAITING_CAPTCHA
            await self._send_photo(update, result, "🔒 보안문자를 입력해주세요.")
            return

        if not result:
            await self._send_text(
                update, "로그인에 실패했습니다. ID/비밀번호를 확인해주세요."
            )
            await self._cleanup_session(context)
            return

        # Login succeeded — navigate to seat selection
        await self._navigate_and_show_seats(update, context)

    async def _navigate_and_show_seats(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Navigate to showtime and show seat map."""
        session: BookingSession = context.user_data["booking_session"]

        await self._send_text(update, "💺 좌석 배치도를 불러오는 중...")

        try:
            ok = await session.navigate_to_showtime(
                theater_id=self.state.theater_id,
                movie_id=self.state.movie_id,
                showtime=self.state.showtime,
                play_date=self.state.play_date
                or datetime.now().strftime("%Y%m%d"),
            )
        except Exception:
            logger.exception("Failed to navigate to showtime")
            await self._send_text(update, "좌석 화면으로 이동에 실패했습니다.")
            await self._cleanup_session(context)
            return

        if not ok:
            await self._send_text(update, "좌석 화면으로 이동에 실패했습니다.")
            await self._cleanup_session(context)
            return

        try:
            screenshot = await session.get_seat_map_screenshot()
        except Exception:
            logger.exception("Failed to capture seat map")
            await self._send_text(update, "좌석 배치도를 가져올 수 없습니다.")
            await self._cleanup_session(context)
            return

        self.state.phase = BookingPhase.SELECTING_SEATS
        await self._send_photo(
            update,
            screenshot,
            "💺 좌석을 선택해주세요.\n예: F7 F8\n(공백으로 구분, '취소'로 취소)",
        )

    async def _handle_captcha(
        self,
        text: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle CAPTCHA answer (deterministic, no LLM)."""
        session: BookingSession = context.user_data["booking_session"]

        try:
            ok = await session.submit_captcha(text.strip())
        except Exception:
            logger.exception("CAPTCHA submission failed")
            await self._send_text(update, "보안문자 처리 중 오류가 발생했습니다.")
            await self._cleanup_session(context)
            return

        if not ok:
            # Retry login to get a new CAPTCHA
            try:
                result = await session.login()
                if isinstance(result, bytes):
                    await self._send_photo(
                        update, result, "틀렸습니다. 다시 입력해주세요."
                    )
                    return
            except Exception:
                pass
            await self._send_text(update, "로그인에 실패했습니다.")
            await self._cleanup_session(context)
            return

        # CAPTCHA passed — navigate to seats
        await self._navigate_and_show_seats(update, context)

    async def _handle_seat_input(
        self,
        text: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle seat selection text (deterministic, no LLM)."""
        seats = re.split(r"[,\s]+", text.strip().upper())
        seats = [s for s in seats if s]

        if not seats:
            await self._send_text(update, "좌석을 입력해주세요. 예: F7 F8")
            return

        session: BookingSession = context.user_data["booking_session"]

        try:
            ok = await session.select_seats(seats)
        except Exception:
            logger.exception("Seat selection failed")
            await self._send_text(update, "좌석 선택 중 오류가 발생했습니다.")
            await self._cleanup_session(context)
            return

        if not ok:
            await self._send_text(
                update,
                "좌석 선택에 실패했습니다. 이미 선택된 좌석이거나 유효하지 않습니다.\n다시 입력해주세요.",
            )
            return

        self.state.seats = seats

        # Show payment methods
        try:
            methods = await session.get_payment_methods()
        except Exception:
            logger.exception("Failed to get payment methods")
            await self._send_text(update, "결제 수단을 불러올 수 없습니다.")
            await self._cleanup_session(context)
            return

        self.state.available_payment_methods = methods
        self.state.phase = BookingPhase.CHOOSING_PAYMENT

        buttons = [
            [InlineKeyboardButton(m, callback_data=f"nlpay:{m}")]
            for m in methods
        ]
        await self._send_text(
            update,
            f"💳 좌석 {', '.join(seats)} 선택 완료.\n결제 수단을 선택하세요.",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def handle_payment(
        self,
        method: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle payment method selection (from callback query)."""
        session: BookingSession = context.user_data.get("booking_session")
        if not session:
            await self._send_text(update, "예매 세션이 만료되었습니다.")
            return

        self.state.payment_method = method
        await self._send_text(update, f"💳 {method}(으)로 결제 진행 중...")

        try:
            result = await session.start_payment(method)
        except Exception:
            logger.exception("Payment failed")
            await self._send_text(update, "결제 중 오류가 발생했습니다.")
            await self._cleanup_session(context)
            return

        if isinstance(result, bytes):
            # Extra auth needed (SMS, app confirm, etc.)
            self.state.phase = BookingPhase.AWAITING_AUTH
            await self._send_photo(
                update,
                result,
                "🔐 인증이 필요합니다. 인증번호를 입력해주세요.\n"
                "(또는 앱 인증 완료 후 '완료' 입력)",
            )
            return

        if not result:
            await self._send_text(update, "결제에 실패했습니다.")
            await self._cleanup_session(context)
            return

        # Payment succeeded!
        await self._show_confirmation(update, context)

    async def _handle_auth_code(
        self,
        text: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle auth code submission (deterministic, no LLM)."""
        session: BookingSession = context.user_data.get("booking_session")
        if not session:
            await self._send_text(update, "예매 세션이 만료되었습니다.")
            return

        try:
            ok = await session.submit_auth_code(text.strip())
        except Exception:
            logger.exception("Auth code submission failed")
            await self._send_text(update, "인증 처리 중 오류가 발생했습니다.")
            await self._cleanup_session(context)
            return

        if not ok:
            await self._send_text(update, "인증에 실패했습니다. 다시 입력해주세요.")
            return

        await self._show_confirmation(update, context)

    async def _show_confirmation(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Send booking confirmation screenshot, directions link, and reset."""
        session: BookingSession = context.user_data.get("booking_session")
        chat_id = self._get_chat_id(update)

        # Build confirmation caption
        caption = (
            f"✅ 예매 완료!\n"
            f"🎬 {self.state.movie_name or ''}\n"
            f"🕐 {self.state.showtime or ''}\n"
            f"💺 {', '.join(self.state.seats or [])}"
        )

        try:
            screenshot = await session.get_confirmation_screenshot()
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=io.BytesIO(screenshot),
                caption=caption,
            )
        except Exception:
            logger.exception("Failed to get confirmation")
            await context.bot.send_message(
                chat_id=chat_id,
                text="✅ 예매가 완료된 것으로 보입니다. 해당 사이트에서 직접 확인해주세요.",
            )

        # Send Naver Directions link if we have both user and theater locations
        await self._send_directions(chat_id, context)

        self.state.phase = BookingPhase.COMPLETED
        await self._cleanup_session(context)

    async def _send_directions(
        self, chat_id: int, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Send Naver Maps directions link after booking confirmation."""
        state = self.state
        if (
            state.user_latitude is not None
            and state.user_longitude is not None
            and state.theater_latitude is not None
            and state.theater_longitude is not None
            and state.theater_name
        ):
            try:
                directions_msg = format_directions_message(
                    start_lat=state.user_latitude,
                    start_lng=state.user_longitude,
                    dest_lat=state.theater_latitude,
                    dest_lng=state.theater_longitude,
                    dest_name=state.theater_name,
                )
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=directions_msg,
                )
            except Exception:
                logger.exception("Failed to send directions link")

    # ------------------------------------------------------------------
    # Cancel & cleanup
    # ------------------------------------------------------------------

    async def _cancel(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Cancel booking and reset."""
        await self._cleanup_session(context)
        await self._send_text(update, "❌ 예매가 취소되었습니다.")

    async def _cleanup_session(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Clean up any active booking session."""
        session: BookingSession | None = context.user_data.pop(
            "booking_session", None
        )
        if session:
            try:
                await session.cleanup()
            except Exception:
                logger.exception("Session cleanup failed")
        self.state.reset()

    # ------------------------------------------------------------------
    # Telegram helpers
    # ------------------------------------------------------------------

    def _get_chat_id(self, update: Update) -> int:
        """Get chat ID from update."""
        if update.callback_query:
            return update.callback_query.message.chat_id
        return update.message.chat_id

    async def _send_text(
        self,
        update: Update,
        text: str,
        reply_markup=None,
    ) -> None:
        """Send a text message to the user."""
        chat_id = self._get_chat_id(update)
        if update.callback_query:
            await update.callback_query.message.reply_text(
                text, reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(text, reply_markup=reply_markup)

    async def _send_photo(
        self,
        update: Update,
        photo_bytes: bytes,
        caption: str,
    ) -> None:
        """Send a photo to the user."""
        chat_id = self._get_chat_id(update)
        # Use context.bot for sending photos with BytesIO
        # Access bot through update
        bot = update.get_bot()
        await bot.send_photo(
            chat_id=chat_id,
            photo=io.BytesIO(photo_bytes),
            caption=caption,
        )
