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
    """Capture Lotte Cinema seat map via the ticketing page minimap popup.

    Lotte Cinema ticketing flow (as of Feb 2026):

    1. Navigate to ``/NLCHS/Ticketing`` (jQuery-based, no login required for
       Step 1).
    2. Select cinema from ``.basicCinemaScroll li a``.
    3. Wait for schedule load, then select movie from ``.movieSelect li a``.
    4. Select showtime from ``a[role="button"]`` matching ``dd.time strong``.
    5. A popup (``#layerReserveStep01``) appears with a **minimap** showing
       seat availability (``sel p0`` = available, ``sel p0 completed`` = sold).
    6. Dismiss any inner info popup ("알려드립니다") if present.
    7. Screenshot the popup element.

    No login is required — the minimap is visible in Step 1.
    """
    page = await _new_page("lotte")

    try:
        await page.goto(
            "https://www.lottecinema.co.kr/NLCHS/Ticketing",
            wait_until="networkidle",
            timeout=30_000,
        )
        await page.wait_for_timeout(3000)

        # --- Select cinema ---
        # Strip chain prefix for matching ("건대입구 롯데시네마" → "건대입구")
        short_name = (
            theater_name.replace("롯데시네마", "")
            .replace("롯데시네마", "")
            .strip()
        )
        cinema_link = page.locator(
            f".basicCinemaScroll li a:has-text('{short_name}')"
        ).first
        try:
            await cinema_link.click(timeout=5000)
            logger.info("Lotte: clicked cinema '%s'", short_name)
        except Exception:
            # Fallback: try partial text match across all cinema links
            clicked = await page.evaluate(
                """(name) => {
                    const links = document.querySelectorAll('.basicCinemaScroll li a');
                    for (const a of links) {
                        if (a.textContent.trim().includes(name)) {
                            a.click();
                            return true;
                        }
                    }
                    return false;
                }""",
                short_name,
            )
            if not clicked:
                return SeatMapResult(
                    success=False,
                    screenshot=b"",
                    error=f"롯데시네마 '{short_name}' 극장을 찾을 수 없습니다",
                )
            logger.info("Lotte: clicked cinema '%s' (JS fallback)", short_name)

        await page.wait_for_timeout(4000)

        # --- Select movie ---
        movie_link = page.locator(
            f".movieSelect li a:has-text('{movie_name}')"
        ).first
        try:
            await movie_link.click(timeout=5000)
            logger.info("Lotte: clicked movie '%s'", movie_name)
        except Exception:
            # Fallback: JS text match
            clicked = await page.evaluate(
                """(name) => {
                    const links = document.querySelectorAll('.movieSelect li a, .movieScroll li a');
                    for (const a of links) {
                        if (a.textContent.includes(name)) {
                            a.click();
                            return true;
                        }
                    }
                    return false;
                }""",
                movie_name,
            )
            if not clicked:
                return SeatMapResult(
                    success=False,
                    screenshot=b"",
                    error=f"롯데시네마에서 '{movie_name}' 영화를 찾을 수 없습니다",
                )
            logger.info("Lotte: clicked movie '%s' (JS fallback)", movie_name)

        await page.wait_for_timeout(4000)

        # --- Select showtime ---
        # Showtime links: <a role="button"> containing <dd class="time"><strong>HH:MM</strong></dd>
        # and optionally <dd class="hall">screen_name</dd>
        clicked_time = await page.evaluate(
            """([targetTime, targetHall]) => {
                const links = document.querySelectorAll('.timeScroll a[role="button"]');
                // First pass: match time + hall
                for (const a of links) {
                    const timeEl = a.querySelector('dd.time strong');
                    const hallEl = a.querySelector('dd.hall');
                    if (!timeEl) continue;
                    const time = timeEl.textContent.trim();
                    const hall = hallEl ? hallEl.textContent.trim() : '';
                    if (time === targetTime && (!targetHall || hall.includes(targetHall))) {
                        a.click();
                        return true;
                    }
                }
                // Second pass: match time only
                for (const a of links) {
                    const timeEl = a.querySelector('dd.time strong');
                    if (timeEl && timeEl.textContent.trim() === targetTime) {
                        a.click();
                        return true;
                    }
                }
                return false;
            }""",
            [start_time, screen_name],
        )

        if not clicked_time:
            return SeatMapResult(
                success=False,
                screenshot=b"",
                error=f"롯데시네마 상영 시간 {start_time}을 찾을 수 없습니다",
            )

        logger.info("Lotte: clicked showtime %s", start_time)
        await page.wait_for_timeout(3000)

        # --- Dismiss "알려드립니다" info popup if present ---
        # This overlay (#layerPopupMulti) sits *above* #layerReserveStep01
        # and appears for certain screens (e.g. 샤롯데).
        for _ in range(3):
            try:
                confirm = page.locator(
                    "#layerPopupMulti button.btnCloseLayerMulti:visible, "
                    "#layerPopupMulti button:has-text('확인'):visible"
                ).first
                if await confirm.is_visible(timeout=800):
                    await confirm.click()
                    logger.debug("Lotte: dismissed layerPopupMulti overlay")
                    await page.wait_for_timeout(800)
                    continue
            except Exception:
                pass
            break

        # --- Screenshot the popup ---
        popup = page.locator("#layerReserveStep01")
        try:
            await popup.wait_for(state="visible", timeout=5000)
            screenshot = await popup.screenshot(type="png")
            logger.info(
                "Lotte: captured minimap popup (%d bytes)", len(screenshot)
            )
        except Exception:
            # Fallback: full viewport
            logger.info("Lotte: popup not found, taking full screenshot")
            screenshot = await page.screenshot(
                type="png",
                clip={"x": 0, "y": 0, "width": 1280, "height": 900},
            )

        return SeatMapResult(success=True, screenshot=screenshot)

    except PwTimeout:
        return SeatMapResult(
            success=False,
            screenshot=b"",
            error="롯데시네마 좌석 페이지 로딩 시간 초과",
        )
    except Exception as e:
        logger.exception("Lotte seat map failed")
        return SeatMapResult(
            success=False,
            screenshot=b"",
            error=f"롯데시네마 좌석 배치도 로딩 실패: {e}",
        )
    finally:
        await page.close()


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
    """Capture CGV seat map via the booking page.

    CGV requires login to view the seat selection page, and the login page
    frequently shows CAPTCHA.  When login succeeds (session cookies from a
    previous manual login may still be valid), we navigate through the SPA
    booking flow: select theater → click showtime → screenshot seat page.

    If login fails due to CAPTCHA, we fall back to a screenshot of the
    schedule page which shows remaining seat counts per showtime.
    """
    page = await _new_page("cgv")

    try:
        # --- Login ---
        from cinepyle.browser.booking_history import _ensure_cgv_login

        logged_in = await _ensure_cgv_login(page)

        # --- Navigate to booking page ---
        await page.goto(
            "https://cgv.co.kr/cnm/movieBook/cinema",
            wait_until="networkidle",
            timeout=30_000,
        )
        await page.wait_for_timeout(3000)

        # --- Select theater ---
        short_name = (
            theater_name
            .replace("CGV", "")
            .replace("cgv", "")
            .strip()
        )
        try:
            theater_btn = page.get_by_text(short_name, exact=True).first
            await theater_btn.click(timeout=5000)
            clicked_theater = True
        except Exception:
            # Fallback: partial text match via JS
            clicked_theater = await page.evaluate(
                """(name) => {
                    const btns = document.querySelectorAll('button');
                    for (const b of btns) {
                        if (b.textContent.trim().includes(name) && b.offsetWidth > 0) {
                            b.click();
                            return true;
                        }
                    }
                    return false;
                }""",
                short_name,
            )
        if not clicked_theater:
            return SeatMapResult(
                success=False,
                screenshot=b"",
                error=f"CGV '{short_name}' 극장을 찾을 수 없습니다",
            )

        logger.info("CGV: clicked theater '%s'", short_name)
        await page.wait_for_timeout(4000)

        if not logged_in:
            # Not logged in — screenshot the schedule page as fallback
            logger.info("CGV: no login, capturing schedule page as fallback")
            screenshot = await page.screenshot(
                type="png",
                clip={"x": 0, "y": 0, "width": 1280, "height": 900},
            )
            return SeatMapResult(
                success=True,
                screenshot=screenshot,
                error="CGV 로그인 불가 (CAPTCHA) — 잔여좌석 현황 페이지입니다",
            )

        # --- Click showtime ---
        clicked_time = await page.evaluate(
            """(targetTime) => {
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    const text = btn.textContent.trim();
                    if (text.includes(targetTime) && !btn.disabled
                        && !text.includes('예매종료') && btn.offsetWidth > 0) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }""",
            start_time,
        )

        if not clicked_time:
            # Fallback: screenshot the schedule page
            logger.info("CGV: showtime %s not found, capturing schedule page", start_time)
            screenshot = await page.screenshot(
                type="png",
                clip={"x": 0, "y": 0, "width": 1280, "height": 900},
            )
            return SeatMapResult(
                success=True,
                screenshot=screenshot,
                error=f"CGV {start_time} 시간을 찾을 수 없어 상영 정보 페이지입니다",
            )

        logger.info("CGV: clicked showtime %s", start_time)

        # --- Wait for seat page ---
        await page.wait_for_timeout(5000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass

        # Dismiss any login modals that might still appear
        await page.evaluate(
            """() => {
                const modals = document.querySelectorAll('[class*="modal"]');
                modals.forEach(m => {
                    if (m.offsetWidth > 0 && m.textContent.includes('로그인')) {
                        const close = m.querySelector('button, [class*="close"]');
                        if (close) close.click();
                    }
                });
            }"""
        )
        await page.wait_for_timeout(2000)

        # --- Screenshot ---
        screenshot = await page.screenshot(
            type="png",
            clip={"x": 0, "y": 0, "width": 1280, "height": 900},
        )
        logger.info("CGV: captured seat map screenshot (%d bytes)", len(screenshot))

        return SeatMapResult(success=True, screenshot=screenshot)

    except PwTimeout:
        return SeatMapResult(
            success=False,
            screenshot=b"",
            error="CGV 좌석 페이지 로딩 시간 초과",
        )
    except Exception as e:
        logger.exception("CGV seat map failed")
        return SeatMapResult(
            success=False,
            screenshot=b"",
            error=f"CGV 좌석 배치도 로딩 실패: {e}",
        )
    finally:
        await page.close()
