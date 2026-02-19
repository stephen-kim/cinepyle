"""Seat map screenshot capture for CGV, Lotte Cinema, MegaBox.

Navigates to each chain's booking page via Playwright, selects the
correct theater/date/movie/showtime, and captures a screenshot of
the seat layout.  MegaBox requires login; Lotte/CGV are not yet supported.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from playwright.async_api import Frame, Page, TimeoutError as PwTimeout

from cinepyle.browser.manager import BrowserManager

logger = logging.getLogger(__name__)

_SEAT_MAP_TIMEOUT = 30_000  # 30 seconds overall timeout


@dataclass
class SeatMapResult:
    """Result of a seat map screenshot attempt."""

    success: bool
    screenshot: bytes  # PNG image data (empty if failed)
    error: str = ""


async def capture_seat_map(
    chain: str,
    theater_code: str,
    theater_name: str,
    movie_name: str,
    start_time: str,
    screen_id: str,
    screen_name: str,
    date_str: str,
    remaining_seats: int = 0,
    meta: dict | None = None,
    schedule_id: str = "",
) -> SeatMapResult:
    """Capture a seat map screenshot for a specific showtime.

    Dispatches to chain-specific implementations.
    """
    chain_handlers = {
        "cgv": _capture_cgv,
        "lotte": _capture_lotte,
        "megabox": _capture_megabox,
    }
    handler = chain_handlers.get(chain)
    if not handler:
        return SeatMapResult(
            success=False,
            screenshot=b"",
            error=f"좌석 배치도를 지원하지 않는 체인: {chain}",
        )

    try:
        return await asyncio.wait_for(
            handler(
                theater_code=theater_code,
                theater_name=theater_name,
                movie_name=movie_name,
                start_time=start_time,
                screen_id=screen_id,
                screen_name=screen_name,
                date_str=date_str,
                remaining_seats=remaining_seats,
                meta=meta,
                schedule_id=schedule_id,
            ),
            timeout=45,
        )
    except asyncio.TimeoutError:
        return SeatMapResult(
            success=False,
            screenshot=b"",
            error="좌석 배치도 로딩 시간이 초과되었습니다",
        )
    except Exception as e:
        logger.exception("Seat map capture failed for %s", chain)
        return SeatMapResult(
            success=False,
            screenshot=b"",
            error=f"좌석 배치도 캡처 실패: {e}",
        )


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


async def _new_page(context_name: str = "seat_map") -> Page:
    """Create a new page in the given browser context."""
    mgr = BrowserManager.instance()
    ctx = await mgr.get_context(context_name)
    page = await ctx.new_page()
    await page.set_viewport_size({"width": 1280, "height": 900})
    return page


async def _close_popups(page: Page, max_rounds: int = 5) -> None:
    """Dismiss common popups and cookie banners.

    MegaBox in particular shows multiple sequential popups (parking info,
    age rating, time warnings).  We loop up to *max_rounds* times to
    catch popups that appear after earlier ones are dismissed.
    """
    popup_selectors = [
        # MegaBox alert-popup "확인" button (age rating, parking, etc.)
        ".alert-popup button.confirm",
        ".alert-popup .btn-close",
        ".alert-popup button:has-text('확인')",
        # Generic patterns
        "button:has-text('닫기')",
        "button:has-text('확인')",
        ".popup-close",
        ".btn-close",
        "[class*='popup'] button",
        "[class*='modal'] .close",
        "[class*='layer'] .close",
    ]

    for _round in range(max_rounds):
        closed_any = False
        for sel in popup_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=300):
                    await btn.click()
                    await page.wait_for_timeout(400)
                    closed_any = True
            except Exception:
                pass
        if not closed_any:
            break
        # Brief pause for next popup to appear
        await page.wait_for_timeout(500)


# ---------------------------------------------------------------------------
# MegaBox
# ---------------------------------------------------------------------------


async def _close_megabox_popups(
    page: Page, seat_frame: Frame | None = None
) -> None:
    """Dismiss MegaBox popups on the main page and inside the seat iframe.

    MegaBox shows sequential popups when entering the booking page:
    1. **Main page**: parking info alert-popup (``<section class="alert-popup">``)
    2. **Seat iframe** (``frameBokdMSeat``): age rating popup (12세이상관람가)
       with a ``button.close-layer`` or ``button:has-text('확인')``

    We dismiss main-page popups first, then check the seat iframe.
    """
    # --- Main page popups ---
    for _round in range(5):
        btn = page.locator(".alert-popup button.confirm:visible").first
        try:
            if await btn.is_visible(timeout=500):
                await btn.click()
                await page.wait_for_timeout(800)
                continue
        except Exception:
            pass
        break

    # --- Seat iframe popups ---
    frame = seat_frame or page.frame("frameBokdMSeat")
    if not frame:
        return

    for _round in range(5):
        try:
            # The age rating popup button: "확인" with class "button purple close-layer"
            btn = frame.locator(
                "button.close-layer:visible, "
                "button.confirm:visible, "
                "button:has-text('확인'):visible"
            ).first
            if await btn.is_visible(timeout=500):
                await btn.click()
                logger.debug("MegaBox: closed iframe popup (round %d)", _round)
                await page.wait_for_timeout(800)
                continue
        except Exception:
            pass
        break


async def _capture_megabox(
    theater_code: str,
    theater_name: str,
    movie_name: str,
    start_time: str,
    screen_id: str,
    screen_name: str,
    date_str: str,
    remaining_seats: int = 0,
    meta: dict | None = None,
    schedule_id: str = "",
) -> SeatMapResult:
    """Capture MegaBox seat map via booking timetable navigation.

    MegaBox booking flow (as of Feb 2026):

    1. Login required — reuses ``_ensure_megabox_login`` from booking_history.
    2. Navigate to ``/booking/timetable?brchNo=...&playDe=...``
    3. Click the ``<a>`` inside ``<td play-schdl-no="...">`` for the target
       showtime.
    4. A parking-info popup appears on the **main page** → dismiss it.
    5. The seat selection page loads at ``/booking`` with the actual seat grid
       inside an **iframe** named ``frameBokdMSeat``.
    6. An age-rating popup (12세이상관람가) appears **inside the iframe**
       → dismiss it.
    7. Capture the full-page screenshot showing the seat map.
    """
    page = await _new_page("megabox")

    try:
        # --- Login ---
        from cinepyle.browser.booking_history import _ensure_megabox_login

        logged_in = await _ensure_megabox_login(page)
        if not logged_in:
            return SeatMapResult(
                success=False,
                screenshot=b"",
                error="메가박스 로그인 정보가 설정되지 않았습니다 (MEGABOX_ID 환경변수)",
            )

        # --- Navigate to timetable ---
        play_de = date_str.replace("-", "")
        url = (
            f"https://www.megabox.co.kr/booking/timetable"
            f"?brchNo={theater_code}&brchNo1={theater_code}&playDe={play_de}"
        )
        await page.goto(url, wait_until="networkidle", timeout=20_000)
        await _close_popups(page)
        await page.wait_for_timeout(2000)

        # --- Click showtime ---
        clicked = False

        # Strategy 1: schedule_id attribute (most precise)
        if schedule_id:
            td = page.locator(f'td[play-schdl-no="{schedule_id}"]')
            if await td.count() > 0:
                link = td.locator("a").first
                await link.click()
                clicked = True
                logger.info("MegaBox: clicked schedule_id=%s", schedule_id)

        # Strategy 2: brch-no + theab-no + time match, then time-only fallback
        if not clicked:
            clicked = await page.evaluate(
                """([brchNo, theabNo, startTime]) => {
                    const tds = document.querySelectorAll(
                        'td[brch-no="' + brchNo + '"][theab-no="' + theabNo + '"]'
                    );
                    for (const td of tds) {
                        const timeEl = td.querySelector('p.time');
                        if (timeEl && timeEl.textContent.trim() === startTime) {
                            const link = td.querySelector('a');
                            if (link) { link.click(); return true; }
                        }
                    }
                    const allTds = document.querySelectorAll('td[play-schdl-no]');
                    for (const td of allTds) {
                        const timeEl = td.querySelector('p.time');
                        if (timeEl && timeEl.textContent.trim() === startTime) {
                            const link = td.querySelector('a');
                            if (link) { link.click(); return true; }
                        }
                    }
                    return false;
                }""",
                [theater_code, screen_id, start_time],
            )

        if not clicked:
            return SeatMapResult(
                success=False,
                screenshot=b"",
                error=f"메가박스 상영 시간 {start_time}을 찾을 수 없습니다",
            )

        # --- Wait for seat page & dismiss popups ---
        # First popup (parking info) appears on the main page before navigation
        await page.wait_for_timeout(2000)
        await _close_megabox_popups(page)

        # Wait for the seat page to finish loading (URL → /booking)
        await page.wait_for_load_state("networkidle", timeout=15_000)
        await page.wait_for_timeout(3000)

        # Dismiss iframe popups (age rating, etc.)
        seat_frame = page.frame("frameBokdMSeat")
        if seat_frame:
            await _close_megabox_popups(page, seat_frame)
            await page.wait_for_timeout(1000)

        if "booking" not in page.url:
            logger.warning("MegaBox: unexpected URL after click: %s", page.url)

        # --- Screenshot ---
        # Full viewport screenshot is the most reliable since the seat grid
        # is inside an iframe and element-level screenshot of cross-origin
        # iframes can be tricky.
        screenshot = await page.screenshot(
            type="png",
            clip={"x": 0, "y": 0, "width": 1280, "height": 900},
        )
        logger.info("MegaBox: captured seat map screenshot (%d bytes)", len(screenshot))

        return SeatMapResult(success=True, screenshot=screenshot)

    except PwTimeout:
        return SeatMapResult(
            success=False,
            screenshot=b"",
            error="메가박스 좌석 페이지 로딩 시간 초과",
        )
    except Exception as e:
        logger.exception("MegaBox seat map failed")
        return SeatMapResult(
            success=False,
            screenshot=b"",
            error=f"메가박스 좌석 배치도 로딩 실패: {e}",
        )
    finally:
        await page.close()


# ---------------------------------------------------------------------------
# Lotte Cinema
# ---------------------------------------------------------------------------


async def _capture_lotte(
    theater_code: str,
    theater_name: str,
    movie_name: str,
    start_time: str,
    screen_id: str,
    screen_name: str,
    date_str: str,
    remaining_seats: int = 0,
    meta: dict | None = None,
    schedule_id: str = "",
) -> SeatMapResult:
    """Capture Lotte Cinema seat map."""
    # TODO: implement Lotte Cinema seat map navigation
    return SeatMapResult(
        success=False,
        screenshot=b"",
        error="롯데시네마 좌석 배치도는 아직 지원되지 않습니다",
    )


# ---------------------------------------------------------------------------
# CGV
# ---------------------------------------------------------------------------


async def _capture_cgv(
    theater_code: str,
    theater_name: str,
    movie_name: str,
    start_time: str,
    screen_id: str,
    screen_name: str,
    date_str: str,
    remaining_seats: int = 0,
    meta: dict | None = None,
    schedule_id: str = "",
) -> SeatMapResult:
    """Capture CGV seat map."""
    # TODO: implement CGV seat map navigation
    return SeatMapResult(
        success=False,
        screenshot=b"",
        error="CGV 좌석 배치도는 아직 지원되지 않습니다",
    )
