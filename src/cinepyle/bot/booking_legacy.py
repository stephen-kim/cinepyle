"""Telegram conversational booking handler.

Flow:
  /book → chain → theater → movie → showtime → login → seats → payment → done
"""

import io
import logging
import re
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from cinepyle.booking.base import BookingSession
from cinepyle.config import (
    CGV_ID,
    CGV_PASSWORD,
    LOTTECINEMA_ID,
    LOTTECINEMA_PASSWORD,
    MEGABOX_ID,
    MEGABOX_PASSWORD,
)
from cinepyle.scrapers.browser import get_page
from cinepyle.theaters import cgv, cineq, lotte, megabox

logger = logging.getLogger(__name__)

# Conversation states
CHAIN, THEATER, MOVIE, SHOWTIME, LOGIN, CAPTCHA, SEATS, PAYMENT, AUTH = range(9)

# Chain registry: chain_key → (display_name, theater_module, credentials)
CHAINS: dict[str, dict] = {
    "cgv": {
        "name": "CGV",
        "module": cgv,
        "creds": (CGV_ID, CGV_PASSWORD),
    },
    "lotte": {
        "name": "롯데시네마",
        "module": lotte,
        "creds": (LOTTECINEMA_ID, LOTTECINEMA_PASSWORD),
    },
    "megabox": {
        "name": "메가박스",
        "module": megabox,
        "creds": (MEGABOX_ID, MEGABOX_PASSWORD),
    },
    "cineq": {
        "name": "씨네Q",
        "module": cineq,
        "creds": ("", ""),  # CineQ may not require login
    },
}

BOOKING_TIMEOUT = 300  # 5 minutes


# ------------------------------------------------------------------
# Helper to create a BookingSession for a given chain
# ------------------------------------------------------------------

async def _create_session(chain_key: str) -> BookingSession:
    """Create the appropriate BookingSession for a chain."""
    page = await get_page()
    info = CHAINS[chain_key]
    uid, pw = info["creds"]

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


async def _cleanup_session(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clean up any active booking session in user_data."""
    session: BookingSession | None = context.user_data.pop("booking_session", None)
    if session:
        await session.cleanup()
    context.user_data.pop("booking_info", None)


# ------------------------------------------------------------------
# Step 1: /book → Chain selection
# ------------------------------------------------------------------

async def book_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: show chain selection."""
    # Clean up any previous session
    await _cleanup_session(context)

    buttons = [
        [
            InlineKeyboardButton("CGV", callback_data="chain:cgv"),
            InlineKeyboardButton("롯데시네마", callback_data="chain:lotte"),
        ],
        [
            InlineKeyboardButton("메가박스", callback_data="chain:megabox"),
            InlineKeyboardButton("씨네Q", callback_data="chain:cineq"),
        ],
    ]
    await update.message.reply_text(
        "🎬 예매할 영화관을 선택하세요.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return CHAIN


# ------------------------------------------------------------------
# Step 2: Chain selected → Theater list
# ------------------------------------------------------------------

async def chain_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User picked a chain. Show theater list."""
    query = update.callback_query
    await query.answer()

    chain_key = query.data.split(":")[1]
    chain_info = CHAINS[chain_key]
    module = chain_info["module"]

    context.user_data["booking_info"] = {"chain": chain_key}

    try:
        theaters = module.get_theater_list()
    except Exception:
        logger.exception("Failed to get theater list for %s", chain_key)
        await query.edit_message_text("극장 목록을 가져오는데 실패했습니다.")
        return ConversationHandler.END

    # Store theaters for lookup
    context.user_data["booking_theaters"] = theaters

    # Show first 10 theaters (paginated later if needed)
    buttons = []
    for i, t in enumerate(theaters[:20]):
        name = t.get("TheaterName", t.get("brchNm", ""))
        tid = t.get("TheaterCode", t.get("TheaterID", t.get("brchNo", str(i))))
        buttons.append([InlineKeyboardButton(name, callback_data=f"theater:{tid}")])

    if not buttons:
        await query.edit_message_text("상영 중인 극장이 없습니다.")
        return ConversationHandler.END

    await query.edit_message_text(
        f"🏢 {chain_info['name']} 극장을 선택하세요.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return THEATER


# ------------------------------------------------------------------
# Step 3: Theater selected → Movie list
# ------------------------------------------------------------------

async def theater_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User picked a theater. Show movie list."""
    query = update.callback_query
    await query.answer()

    theater_id = query.data.split(":")[1]
    info = context.user_data["booking_info"]
    info["theater_id"] = theater_id
    chain_key = info["chain"]
    module = CHAINS[chain_key]["module"]

    await query.edit_message_text("🔍 상영 스케줄을 불러오는 중...")

    try:
        schedule = module.get_movie_schedule(theater_id)
    except Exception:
        logger.exception("Failed to get schedule for %s/%s", chain_key, theater_id)
        await query.edit_message_text("스케줄을 가져오는데 실패했습니다.")
        return ConversationHandler.END

    if not schedule:
        await query.edit_message_text("현재 상영 중인 영화가 없습니다.")
        return ConversationHandler.END

    context.user_data["booking_schedule"] = schedule

    buttons = []
    for movie_key, movie_info in schedule.items():
        name = movie_info.get("Name", movie_key)
        buttons.append([InlineKeyboardButton(name, callback_data=f"movie:{movie_key}")])

    await query.edit_message_text(
        "🎬 영화를 선택하세요.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return MOVIE


# ------------------------------------------------------------------
# Step 4: Movie selected → Showtime list
# ------------------------------------------------------------------

async def movie_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User picked a movie. Show available showtimes."""
    query = update.callback_query
    await query.answer()

    movie_key = query.data.split(":", 1)[1]
    info = context.user_data["booking_info"]
    info["movie_id"] = movie_key

    schedule = context.user_data["booking_schedule"]
    movie_info = schedule.get(movie_key, {})
    schedules = movie_info.get("Schedules", [])

    if not schedules:
        await query.edit_message_text("상영 시간이 없습니다.")
        return ConversationHandler.END

    buttons = []
    for i, s in enumerate(schedules):
        start = s.get("StartTime", "")
        remaining = s.get("RemainingSeat", "")
        label = f"{start}"
        if remaining:
            label += f" ({remaining}석)"
        buttons.append([InlineKeyboardButton(label, callback_data=f"time:{i}")])

    info["movie_name"] = movie_info.get("Name", movie_key)

    await query.edit_message_text(
        f"🕐 [{info['movie_name']}] 시간을 선택하세요.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return SHOWTIME


# ------------------------------------------------------------------
# Step 5: Showtime selected → Login
# ------------------------------------------------------------------

async def showtime_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User picked a showtime. Start login and navigate to seat selection."""
    query = update.callback_query
    await query.answer()

    time_idx = int(query.data.split(":")[1])
    info = context.user_data["booking_info"]
    schedule = context.user_data["booking_schedule"]
    movie_info = schedule[info["movie_id"]]
    showtime_info = movie_info["Schedules"][time_idx]

    info["showtime"] = showtime_info["StartTime"]
    info["play_date"] = datetime.now().strftime("%Y%m%d")

    chain_key = info["chain"]

    await query.edit_message_text("🔐 로그인 중...")

    # Create booking session
    session = await _create_session(chain_key)
    context.user_data["booking_session"] = session

    try:
        result = await session.login()
    except Exception:
        logger.exception("Login failed for %s", chain_key)
        await query.edit_message_text("로그인에 실패했습니다.")
        await _cleanup_session(context)
        return ConversationHandler.END

    if isinstance(result, bytes):
        # CAPTCHA — send image and wait for answer
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=io.BytesIO(result),
            caption="🔒 아래 보안문자를 입력해주세요.",
        )
        return CAPTCHA

    if not result:
        await query.edit_message_text("로그인에 실패했습니다. ID/비밀번호를 확인해주세요.")
        await _cleanup_session(context)
        return ConversationHandler.END

    # Login succeeded → navigate to seat selection
    return await _navigate_to_seats(update, context)


# ------------------------------------------------------------------
# Step 5b: CAPTCHA answer
# ------------------------------------------------------------------

async def captcha_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User typed the CAPTCHA answer."""
    answer = update.message.text.strip()
    session: BookingSession = context.user_data["booking_session"]

    try:
        ok = await session.submit_captcha(answer)
    except Exception:
        logger.exception("CAPTCHA submission failed")
        await update.message.reply_text("보안문자 처리 중 오류가 발생했습니다.")
        await _cleanup_session(context)
        return ConversationHandler.END

    if not ok:
        await update.message.reply_text("보안문자가 틀렸습니다. 다시 시도해주세요.")
        # Retry login to get a new CAPTCHA
        result = await session.login()
        if isinstance(result, bytes):
            await context.bot.send_photo(
                chat_id=update.message.chat_id,
                photo=io.BytesIO(result),
                caption="🔒 새 보안문자를 입력해주세요.",
            )
            return CAPTCHA
        await update.message.reply_text("로그인에 실패했습니다.")
        await _cleanup_session(context)
        return ConversationHandler.END

    return await _navigate_to_seats(update, context)


# ------------------------------------------------------------------
# Navigate to seats (shared helper)
# ------------------------------------------------------------------

async def _navigate_to_seats(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Navigate to the seat selection screen and send the seat map."""
    info = context.user_data["booking_info"]
    session: BookingSession = context.user_data["booking_session"]

    chat_id = (
        update.callback_query.message.chat_id
        if update.callback_query
        else update.message.chat_id
    )
    send = context.bot.send_message

    await send(chat_id=chat_id, text="좌석 배치도를 불러오는 중...")

    try:
        ok = await session.navigate_to_showtime(
            theater_id=info["theater_id"],
            movie_id=info["movie_id"],
            showtime=info["showtime"],
            play_date=info["play_date"],
        )
    except Exception:
        logger.exception("Failed to navigate to showtime")
        await send(chat_id=chat_id, text="좌석 화면으로 이동에 실패했습니다.")
        await _cleanup_session(context)
        return ConversationHandler.END

    if not ok:
        await send(chat_id=chat_id, text="좌석 화면으로 이동에 실패했습니다.")
        await _cleanup_session(context)
        return ConversationHandler.END

    try:
        screenshot = await session.get_seat_map_screenshot()
    except Exception:
        logger.exception("Failed to capture seat map")
        await send(chat_id=chat_id, text="좌석 배치도를 가져올 수 없습니다.")
        await _cleanup_session(context)
        return ConversationHandler.END

    await context.bot.send_photo(
        chat_id=chat_id,
        photo=io.BytesIO(screenshot),
        caption="💺 좌석을 선택해주세요.\n예: F7 F8\n(공백으로 구분, /cancel 로 취소)",
    )
    return SEATS


# ------------------------------------------------------------------
# Step 6: Seat selection
# ------------------------------------------------------------------

async def seats_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User typed seat numbers like 'F7 F8'."""
    text = update.message.text.strip().upper()
    seats = re.split(r"[,\s]+", text)
    seats = [s for s in seats if s]

    if not seats:
        await update.message.reply_text("좌석을 입력해주세요. 예: F7 F8")
        return SEATS

    session: BookingSession = context.user_data["booking_session"]

    try:
        ok = await session.select_seats(seats)
    except Exception:
        logger.exception("Seat selection failed")
        await update.message.reply_text("좌석 선택 중 오류가 발생했습니다.")
        await _cleanup_session(context)
        return ConversationHandler.END

    if not ok:
        await update.message.reply_text(
            "좌석 선택에 실패했습니다. 이미 선택된 좌석이거나 유효하지 않습니다.\n다시 입력해주세요."
        )
        return SEATS

    info = context.user_data["booking_info"]
    info["seats"] = seats

    # Show payment methods
    try:
        methods = await session.get_payment_methods()
    except Exception:
        logger.exception("Failed to get payment methods")
        await update.message.reply_text("결제 수단을 불러올 수 없습니다.")
        await _cleanup_session(context)
        return ConversationHandler.END

    if not methods:
        await update.message.reply_text("사용 가능한 결제 수단이 없습니다.")
        await _cleanup_session(context)
        return ConversationHandler.END

    buttons = []
    for m in methods:
        buttons.append([InlineKeyboardButton(m, callback_data=f"pay:{m}")])

    await update.message.reply_text(
        f"💳 좌석 {', '.join(seats)} 선택 완료.\n결제 수단을 선택하세요.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return PAYMENT


# ------------------------------------------------------------------
# Step 7: Payment
# ------------------------------------------------------------------

async def payment_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User picked a payment method."""
    query = update.callback_query
    await query.answer()

    method = query.data.split(":", 1)[1]
    session: BookingSession = context.user_data["booking_session"]

    await query.edit_message_text(f"💳 {method}(으)로 결제 진행 중...")

    try:
        result = await session.start_payment(method)
    except Exception:
        logger.exception("Payment failed")
        await query.edit_message_text("결제 중 오류가 발생했습니다.")
        await _cleanup_session(context)
        return ConversationHandler.END

    if isinstance(result, bytes):
        # Extra auth needed (SMS, app confirm, etc.)
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=io.BytesIO(result),
            caption="🔐 인증이 필요합니다. 인증번호를 입력해주세요.\n(또는 앱 인증 완료 후 '완료' 입력)",
        )
        return AUTH

    if not result:
        await query.edit_message_text("결제에 실패했습니다.")
        await _cleanup_session(context)
        return ConversationHandler.END

    # Payment succeeded!
    return await _show_confirmation(update, context)


# ------------------------------------------------------------------
# Step 7b: Auth code
# ------------------------------------------------------------------

async def auth_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User typed SMS code or '완료'."""
    code = update.message.text.strip()
    session: BookingSession = context.user_data["booking_session"]

    try:
        ok = await session.submit_auth_code(code)
    except Exception:
        logger.exception("Auth code submission failed")
        await update.message.reply_text("인증 처리 중 오류가 발생했습니다.")
        await _cleanup_session(context)
        return ConversationHandler.END

    if not ok:
        await update.message.reply_text("인증에 실패했습니다. 다시 입력해주세요.")
        return AUTH

    return await _show_confirmation(update, context)


# ------------------------------------------------------------------
# Confirmation
# ------------------------------------------------------------------

async def _show_confirmation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Send booking confirmation screenshot and end conversation."""
    session: BookingSession = context.user_data["booking_session"]
    info = context.user_data["booking_info"]

    chat_id = (
        update.callback_query.message.chat_id
        if update.callback_query
        else update.message.chat_id
    )

    try:
        screenshot = await session.get_confirmation_screenshot()
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=io.BytesIO(screenshot),
            caption=(
                f"✅ 예매 완료!\n"
                f"🎬 {info.get('movie_name', '')}\n"
                f"🕐 {info.get('showtime', '')}\n"
                f"💺 {', '.join(info.get('seats', []))}"
            ),
        )
    except Exception:
        logger.exception("Failed to get confirmation")
        await context.bot.send_message(
            chat_id=chat_id,
            text="✅ 예매가 완료된 것으로 보입니다. 해당 사이트에서 직접 확인해주세요.",
        )

    await _cleanup_session(context)
    return ConversationHandler.END


# ------------------------------------------------------------------
# Cancel
# ------------------------------------------------------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the booking at any step."""
    await _cleanup_session(context)
    await update.message.reply_text("❌ 예매가 취소되었습니다.")
    return ConversationHandler.END


# ------------------------------------------------------------------
# Timeout
# ------------------------------------------------------------------

async def timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle conversation timeout."""
    await _cleanup_session(context)
    if update and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⏰ 시간이 초과되어 예매가 취소되었습니다.",
        )
    return ConversationHandler.END


# ------------------------------------------------------------------
# Build the ConversationHandler
# ------------------------------------------------------------------

def build_booking_handler() -> ConversationHandler:
    """Create and return the booking ConversationHandler."""
    return ConversationHandler(
        entry_points=[CommandHandler("book", book_command)],
        states={
            CHAIN: [CallbackQueryHandler(chain_selected, pattern=r"^chain:")],
            THEATER: [CallbackQueryHandler(theater_selected, pattern=r"^theater:")],
            MOVIE: [CallbackQueryHandler(movie_selected, pattern=r"^movie:")],
            SHOWTIME: [CallbackQueryHandler(showtime_selected, pattern=r"^time:")],
            CAPTCHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, captcha_answer)],
            SEATS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seats_input)],
            PAYMENT: [CallbackQueryHandler(payment_selected, pattern=r"^pay:")],
            AUTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_code)],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, timeout),
                CallbackQueryHandler(timeout),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=BOOKING_TIMEOUT,
    )
