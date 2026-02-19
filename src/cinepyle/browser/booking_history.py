"""Booking history scraping for CGV, Lotte Cinema, MegaBox.

All three chains require login to view booking history.  This module
manages login sessions and extracts booking records from each chain's
my-page/history section.

Session cookies are persisted via BrowserManager so re-login is
minimised.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date

from playwright.async_api import Page

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class BookingRecord:
    """A single booking / reservation record."""

    chain: str  # "cgv" | "lotte" | "megabox"
    movie_name: str
    date: str  # "YYYY-MM-DD" or raw string
    time: str  # "HH:MM" or ""
    theater_name: str
    screen_name: str  # e.g., "IMAX관", "1관"
    status: str  # "confirmed" | "cancelled" | "watched" | "unknown"
    booking_number: str  # reservation ID
    seats: list[str] = field(default_factory=list)  # e.g., ["G12", "G13"]


@dataclass
class BookingHistoryResult:
    """Result from a single chain's booking history fetch."""

    chain: str
    records: list[BookingRecord] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# CGV
# ---------------------------------------------------------------------------

CGV_LOGIN_URL = "https://cgv.co.kr/mem/login"
CGV_MYPAGE_URL = "https://cgv.co.kr/cnm/myPage"
CGV_BOOKING_URL = "https://cgv.co.kr/cnm/myPage/myBkng/bkngList"


async def _ensure_cgv_login(page: Page) -> bool:
    """Ensure CGV login session is active.  Returns True if logged in."""
    from cinepyle.config import CGV_ID, CGV_PASSWORD

    if not CGV_ID or not CGV_PASSWORD:
        return False

    # Check if already logged in by looking for login session
    await page.goto(CGV_LOGIN_URL, wait_until="networkidle", timeout=30000)

    # If we're redirected away from login page → already logged in
    if "login" not in page.url.lower() and "mem/login" not in page.url:
        return True

    # Check for CAPTCHA
    page_text = await page.evaluate(
        "() => document.body.innerText.substring(0, 2000)"
    )
    if "자동입력 방지문자" in page_text or "captcha" in page_text.lower():
        logger.warning("CGV login has CAPTCHA — cannot auto-login")
        return False

    # Fill login form
    try:
        # CGV uses ID, not email
        id_input = page.locator("input[type='text']").first
        pw_input = page.locator("input[type='password']").first
        await id_input.fill(CGV_ID)
        await pw_input.fill(CGV_PASSWORD)

        # Submit
        await page.get_by_text("로그인", exact=True).first.click()
        await page.wait_for_load_state("networkidle", timeout=15000)

        # Check if login succeeded
        if "login" in page.url.lower():
            logger.warning("CGV login failed — still on login page")
            return False

        # Save session
        from cinepyle.browser.manager import BrowserManager

        await BrowserManager.instance().save_context("cgv")
        return True
    except Exception:
        logger.exception("CGV login failed")
        return False


async def fetch_cgv_booking_history() -> BookingHistoryResult:
    """Fetch CGV booking history."""
    from cinepyle.browser.manager import BrowserManager
    from cinepyle.config import CGV_ID

    result = BookingHistoryResult(chain="cgv")
    if not CGV_ID:
        result.error = "CGV 로그인 정보가 설정되지 않았습니다 (CGV_ID 환경변수)"
        return result

    mgr = BrowserManager.instance()
    ctx = await mgr.get_context("cgv")
    page = await ctx.new_page()

    try:
        if not await _ensure_cgv_login(page):
            result.error = (
                "CGV 로그인 실패 — CAPTCHA가 있어 자동 로그인이 어렵습니다. "
                "CGV 앱에서 예매 내역을 확인해주세요."
            )
            return result

        # Navigate to booking history
        # Try various mypage URLs (CGV URL structure may vary)
        for url in [CGV_BOOKING_URL, CGV_MYPAGE_URL]:
            await page.goto(url, wait_until="networkidle", timeout=15000)
            if "login" not in page.url.lower():
                break

        result.records = await _parse_cgv_bookings(page)

    except Exception:
        logger.exception("CGV booking history failed")
        result.error = "CGV 예매 내역 조회 실패"
    finally:
        await page.close()

    return result


async def _parse_cgv_bookings(page: Page) -> list[BookingRecord]:
    """Parse booking records from CGV booking history page."""
    records: list[BookingRecord] = []

    # Try to extract from rendered DOM
    items = await page.evaluate(
        """() => {
        // Look for booking list items
        const cards = document.querySelectorAll(
            '[class*="booking"], [class*="reserve"], [class*="ticket"], '
            + '[class*="bkng"], [class*="order"]'
        );
        const results = [];
        for (const card of cards) {
            results.push(card.innerText);
        }
        // If no specific cards found, get main content area
        if (results.length === 0) {
            const main = document.querySelector('main, #content, [class*="content"]');
            if (main) results.push(main.innerText);
        }
        return results;
    }"""
    )

    for item_text in items:
        parsed = _parse_booking_text(item_text, "cgv")
        records.extend(parsed)

    return records


# ---------------------------------------------------------------------------
# Lotte Cinema
# ---------------------------------------------------------------------------

LOTTE_LOGIN_URL = "https://www.lottecinema.co.kr/NLCHS/member/login"
LOTTE_BOOKING_URL = (
    "https://www.lottecinema.co.kr/NLCHS/MyCinema/TicketingOrderList"
)


async def _ensure_lotte_login(page: Page) -> bool:
    """Ensure Lotte Cinema login session is active."""
    from cinepyle.config import LOTTE_ID, LOTTE_PASSWORD

    if not LOTTE_ID or not LOTTE_PASSWORD:
        return False

    await page.goto(LOTTE_BOOKING_URL, wait_until="networkidle", timeout=30000)

    # If not redirected to login → already logged in
    if "login" not in page.url.lower():
        return True

    # Fill login form
    try:
        await page.fill("#txtLoginID", LOTTE_ID)
        await page.fill("#txtLoginPW", LOTTE_PASSWORD)
        await page.click("#btnLogin")
        await page.wait_for_load_state("networkidle", timeout=15000)

        if "login" in page.url.lower():
            logger.warning("Lotte login failed — still on login page")
            return False

        from cinepyle.browser.manager import BrowserManager

        await BrowserManager.instance().save_context("lotte")
        return True
    except Exception:
        logger.exception("Lotte login failed")
        return False


async def fetch_lotte_booking_history() -> BookingHistoryResult:
    """Fetch Lotte Cinema booking history."""
    from cinepyle.browser.manager import BrowserManager
    from cinepyle.config import LOTTE_ID

    result = BookingHistoryResult(chain="lotte")
    if not LOTTE_ID:
        result.error = "롯데시네마 로그인 정보가 설정되지 않았습니다 (LOTTE_ID 환경변수)"
        return result

    mgr = BrowserManager.instance()
    ctx = await mgr.get_context("lotte")
    page = await ctx.new_page()

    try:
        if not await _ensure_lotte_login(page):
            result.error = "롯데시네마 로그인 실패 — 로그인 정보를 확인해주세요"
            return result

        # Navigate to booking history
        await page.goto(LOTTE_BOOKING_URL, wait_until="networkidle", timeout=15000)
        result.records = await _parse_lotte_bookings(page)

    except Exception:
        logger.exception("Lotte booking history failed")
        result.error = "롯데시네마 예매 내역 조회 실패"
    finally:
        await page.close()

    return result


async def _parse_lotte_bookings(page: Page) -> list[BookingRecord]:
    """Parse booking records from Lotte Cinema booking history page."""
    records: list[BookingRecord] = []

    items = await page.evaluate(
        """() => {
        const cards = document.querySelectorAll(
            '.my-ticket-list li, .ticket-list li, '
            + '[class*="booking"] li, [class*="order"] li, '
            + '.movie-info, .ticket-info'
        );
        const results = [];
        for (const card of cards) {
            results.push(card.innerText);
        }
        if (results.length === 0) {
            const main = document.querySelector(
                '.contents-area, .sub-contents, #contents, main'
            );
            if (main) results.push(main.innerText);
        }
        return results;
    }"""
    )

    for item_text in items:
        parsed = _parse_booking_text(item_text, "lotte")
        records.extend(parsed)

    return records


# ---------------------------------------------------------------------------
# MegaBox
# ---------------------------------------------------------------------------

MEGABOX_LOGIN_URL = "https://www.megabox.co.kr"
MEGABOX_LOGIN_API = (
    "https://www.megabox.co.kr/on/oh/ohg/MbLogin/selectLoginSession.do"
)
MEGABOX_BOOKING_URL = "https://www.megabox.co.kr/mypage/bookinglist"


async def _ensure_megabox_login(page: Page) -> bool:
    """Ensure MegaBox login session is active."""
    from cinepyle.config import MEGABOX_ID, MEGABOX_PASSWORD

    if not MEGABOX_ID or not MEGABOX_PASSWORD:
        return False

    # Go to main page and trigger login popup
    await page.goto(MEGABOX_LOGIN_URL, wait_until="networkidle", timeout=30000)

    # Close any popups
    try:
        close_btns = page.locator('[class*="close"], .btn-close, .popup-close')
        for i in range(await close_btns.count()):
            try:
                await close_btns.nth(i).click(timeout=1000)
            except Exception:
                pass
        await asyncio.sleep(0.5)
    except Exception:
        pass

    # Check if already logged in
    session_check = await page.evaluate(
        """async () => {
        try {
            const resp = await fetch('/on/oh/ohg/MbLogin/selectLoginSession.do');
            const data = await resp.json();
            return data.resultMap?.result || 'N';
        } catch { return 'N'; }
    }"""
    )

    if session_check == "Y":
        return True

    # Open login layer
    try:
        await page.evaluate("fn_viewLoginPopup('default','pc')")
        await asyncio.sleep(1)
    except Exception:
        pass

    # Fill login form
    try:
        await page.fill("#ibxMbId", MEGABOX_ID)
        await page.fill("#ibxLoginPwd", MEGABOX_PASSWORD)
        await page.click("#btnLogin")
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(1)

        # Verify login
        session_check = await page.evaluate(
            """async () => {
            try {
                const resp = await fetch('/on/oh/ohg/MbLogin/selectLoginSession.do');
                const data = await resp.json();
                return data.resultMap?.result || 'N';
            } catch { return 'N'; }
        }"""
        )

        if session_check != "Y":
            logger.warning("MegaBox login failed")
            return False

        from cinepyle.browser.manager import BrowserManager

        await BrowserManager.instance().save_context("megabox")
        return True
    except Exception:
        logger.exception("MegaBox login failed")
        return False


async def fetch_megabox_booking_history() -> BookingHistoryResult:
    """Fetch MegaBox booking history."""
    from cinepyle.browser.manager import BrowserManager
    from cinepyle.config import MEGABOX_ID

    result = BookingHistoryResult(chain="megabox")
    if not MEGABOX_ID:
        result.error = "메가박스 로그인 정보가 설정되지 않았습니다 (MEGABOX_ID 환경변수)"
        return result

    mgr = BrowserManager.instance()
    ctx = await mgr.get_context("megabox")
    page = await ctx.new_page()

    try:
        if not await _ensure_megabox_login(page):
            result.error = "메가박스 로그인 실패 — 로그인 정보를 확인해주세요"
            return result

        # Navigate to booking history
        await page.goto(
            MEGABOX_BOOKING_URL, wait_until="networkidle", timeout=15000
        )

        # Check if redirected to main (not logged in)
        if page.url == "https://www.megabox.co.kr/" or "login" in page.url:
            result.error = "메가박스 로그인 세션이 만료되었습니다"
            return result

        result.records = await _parse_megabox_bookings(page)

    except Exception:
        logger.exception("MegaBox booking history failed")
        result.error = "메가박스 예매 내역 조회 실패"
    finally:
        await page.close()

    return result


async def _parse_megabox_bookings(page: Page) -> list[BookingRecord]:
    """Parse booking records from MegaBox booking history page."""
    records: list[BookingRecord] = []

    items = await page.evaluate(
        """() => {
        const cards = document.querySelectorAll(
            '.booking-list li, .my-bkg-list li, '
            + '[class*="booking"] li, .bkg-movie-info, '
            + '.movie-list li, .order-list li'
        );
        const results = [];
        for (const card of cards) {
            results.push(card.innerText);
        }
        if (results.length === 0) {
            const main = document.querySelector(
                '.mypage-content, .contents, #contents, main'
            );
            if (main) results.push(main.innerText);
        }
        return results;
    }"""
    )

    for item_text in items:
        parsed = _parse_booking_text(item_text, "megabox")
        records.extend(parsed)

    return records


# ---------------------------------------------------------------------------
# Common text parser
# ---------------------------------------------------------------------------

# Date patterns: 2026.02.15, 2026-02-15, 2026/02/15
_DATE_PATTERN = re.compile(r"(20\d{2})[./\-](\d{1,2})[./\-](\d{1,2})")
# Time pattern: 14:30, 19:00
_TIME_PATTERN = re.compile(r"(\d{1,2}):(\d{2})")
# Seat pattern: G12, A1, K15
_SEAT_PATTERN = re.compile(r"\b([A-Z]\d{1,2})\b")
# Booking number patterns
_BOOKING_NUM_PATTERN = re.compile(r"(?:예매|예약|주문)\s*(?:번호|NO)\s*[:\s]*(\S+)", re.I)


def _parse_booking_text(text: str, chain: str) -> list[BookingRecord]:
    """Best-effort extraction of booking info from raw text.

    This is a heuristic parser — the actual DOM structure varies
    between chains and may change.  Returns empty list if nothing
    useful can be extracted.
    """
    if not text or len(text.strip()) < 10:
        return []

    # Try to find a date
    date_match = _DATE_PATTERN.search(text)
    if not date_match:
        return []  # No date → probably not a booking record

    date_str = f"{date_match.group(1)}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"

    # Time
    time_match = _TIME_PATTERN.search(text)
    time_str = f"{int(time_match.group(1)):02d}:{time_match.group(2)}" if time_match else ""

    # Seats
    seats = _SEAT_PATTERN.findall(text)

    # Booking number
    bnum_match = _BOOKING_NUM_PATTERN.search(text)
    booking_number = bnum_match.group(1) if bnum_match else ""

    # Status
    status = "unknown"
    if "취소" in text:
        status = "cancelled"
    elif "관람완료" in text or "관람 완료" in text or "이용완료" in text:
        status = "watched"
    elif "예매완료" in text or "예매 완료" in text or "확정" in text or "결제완료" in text:
        status = "confirmed"

    # Movie name — take the first non-empty line that isn't a label
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    movie_name = ""
    theater_name = ""
    screen_name = ""

    skip_labels = {
        "예매",
        "예약",
        "확인",
        "취소",
        "결제",
        "좌석",
        "상영관",
        "극장",
        "날짜",
        "시간",
        "관람완료",
        "예매완료",
        "이용완료",
        "결제완료",
    }

    for line in lines:
        low = line.lower()
        # Skip short label-only lines
        if len(line) < 3 or any(line.startswith(s) for s in skip_labels):
            continue
        # Skip lines with only digits/dates
        if _DATE_PATTERN.match(line) or line.replace(" ", "").isdigit():
            continue

        if not movie_name:
            movie_name = line
        elif not theater_name and ("CGV" in line or "롯데" in line or "메가" in line or "관" in line):
            theater_name = line
        elif not screen_name and "관" in line:
            screen_name = line

    if not movie_name:
        return []

    return [
        BookingRecord(
            chain=chain,
            movie_name=movie_name,
            date=date_str,
            time=time_str,
            theater_name=theater_name,
            screen_name=screen_name,
            status=status,
            booking_number=booking_number,
            seats=seats,
        )
    ]


# ---------------------------------------------------------------------------
# Multi-chain dispatcher
# ---------------------------------------------------------------------------


async def fetch_booking_history(
    chain: str = "",
) -> list[BookingHistoryResult]:
    """Fetch booking history from configured chains.

    If *chain* is empty, query all chains that have credentials set.
    Returns results for each chain (possibly with errors).
    """
    from cinepyle.config import CGV_ID, LOTTE_ID, MEGABOX_ID

    tasks: list[asyncio.Task] = []

    if chain:
        chain_map = {
            "cgv": (CGV_ID, fetch_cgv_booking_history),
            "CGV": (CGV_ID, fetch_cgv_booking_history),
            "lotte": (LOTTE_ID, fetch_lotte_booking_history),
            "롯데시네마": (LOTTE_ID, fetch_lotte_booking_history),
            "롯데": (LOTTE_ID, fetch_lotte_booking_history),
            "megabox": (MEGABOX_ID, fetch_megabox_booking_history),
            "메가박스": (MEGABOX_ID, fetch_megabox_booking_history),
        }
        entry = chain_map.get(chain)
        if entry:
            cred, fetcher = entry
            if cred:
                tasks.append(asyncio.create_task(fetcher()))
            else:
                return [
                    BookingHistoryResult(
                        chain=chain,
                        error=f"{chain} 로그인 정보가 설정되지 않았습니다",
                    )
                ]
        else:
            return [
                BookingHistoryResult(chain=chain, error=f"지원하지 않는 체인: {chain}")
            ]
    else:
        # Query all configured chains
        if CGV_ID:
            tasks.append(asyncio.create_task(fetch_cgv_booking_history()))
        if LOTTE_ID:
            tasks.append(asyncio.create_task(fetch_lotte_booking_history()))
        if MEGABOX_ID:
            tasks.append(asyncio.create_task(fetch_megabox_booking_history()))

    if not tasks:
        return [
            BookingHistoryResult(
                chain="all",
                error=(
                    "로그인 정보가 설정되지 않았습니다.\n"
                    ".env에 CGV_ID, LOTTE_ID, MEGABOX_ID 등을 설정해주세요."
                ),
            )
        ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    out: list[BookingHistoryResult] = []
    for r in results:
        if isinstance(r, BookingHistoryResult):
            out.append(r)
        elif isinstance(r, Exception):
            out.append(
                BookingHistoryResult(chain="unknown", error=f"조회 오류: {r}")
            )

    return out
