"""Telegram bot command handlers."""

import logging

from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from cinepyle.config import KOBIS_API_KEY
from cinepyle.scrapers.boxoffice import fetch_daily_box_office
from cinepyle.theaters.finder import find_nearest_theaters

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    text = (
        "안녕하세요! 영화 알림봇입니다.\n\n"
        "사용 가능한 명령어:\n"
        "/ranking - 오늘의 박스오피스 순위\n"
        "/nearby - 근처 영화관 찾기\n"
        "/book - 영화 예매\n"
        "/help - 도움말\n\n"
        "💬 자연어로도 예매할 수 있어요!\n"
        "예: \"CGV 용산에서 캡틴 아메리카 7시 예매해줘\""
    )
    await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    text = (
        "영화 알림봇 사용법:\n\n"
        "📋 명령어:\n"
        "/ranking - 일일 박스오피스 순위 (영화진흥위원회)\n"
        "/nearby - 근처 영화관 찾기 (위치 전송 필요)\n"
        "/book - 영화 예매 (CGV, 롯데시네마, 메가박스, 씨네Q)\n"
        "/help - 이 도움말 표시\n\n"
        "💬 자연어 예매:\n"
        "명령어 없이 자유롭게 말씀하셔도 됩니다.\n"
        "예: \"메가박스 코엑스에서 영화 보고 싶어\"\n"
        "예: \"CGV 용산 캡틴 아메리카 7시 예매\"\n\n"
        "🔔 자동 알림:\n"
        "- 새로운 영화가 박스오피스에 진입하면 알림 (Watcha 예상 별점 포함)\n"
        "- CGV용산아이파크몰 IMAX 상영 개시 알림"
    )
    await update.message.reply_text(text)


async def ranking_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ranking command -- show daily box office."""
    try:
        movies = fetch_daily_box_office(KOBIS_API_KEY)
    except Exception:
        logger.exception("Failed to fetch box office")
        await update.message.reply_text(
            "박스오피스 정보를 가져오는데 실패했습니다. 잠시 후 다시 시도해주세요."
        )
        return

    lines = [f"{m['rank']}. {m['name']}" for m in movies]
    text = "🎬 일일 박스오피스 순위:\n\n" + "\n".join(lines)
    await update.message.reply_text(text)


async def nearby_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /nearby command -- request location."""
    location_button = KeyboardButton(text="📍 위치 전송", request_location=True)
    keyboard = ReplyKeyboardMarkup(
        [[location_button]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "현재 위치를 전송해주세요.",
        reply_markup=keyboard,
    )


async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle location messages -- find nearby theaters."""
    location = update.message.location
    if location is None:
        return

    latitude = location.latitude
    longitude = location.longitude

    remove_keyboard = ReplyKeyboardRemove()
    await update.message.reply_text(
        "위치를 확인했습니다. 근처 영화관을 검색 중입니다...",
        reply_markup=remove_keyboard,
    )

    try:
        theaters = find_nearest_theaters(latitude, longitude, n=5)
    except Exception:
        logger.exception("Failed to find nearby theaters")
        await update.message.reply_text(
            "영화관 검색에 실패했습니다. 잠시 후 다시 시도해주세요."
        )
        return

    if not theaters:
        await update.message.reply_text("근처에 영화관을 찾을 수 없습니다.")
        return

    lines = []
    for i, t in enumerate(theaters, 1):
        lines.append(f"{i}. {t['TheaterName']} ({t['Chain']})")

    text = "📍 근처 영화관:\n\n" + "\n".join(lines)
    await update.message.reply_text(text)
