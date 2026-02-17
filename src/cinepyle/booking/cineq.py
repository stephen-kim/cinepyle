"""CineQ (씨네Q) booking session.

CineQ uses a popup-based reservation system triggered by
$.desktop.reserve.open({playDate, theaterCode, movieCode, screenPlanId}).
The seat map and payment flow happen inside this popup.
"""

import logging

from playwright.async_api import Page

from cinepyle.booking.base import BookingSession

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cineq.co.kr"
THEATER_URL = f"{BASE_URL}/Theater"


class CineQBookingSession(BookingSession):
    chain_name = "씨네Q"

    def __init__(self, page: Page, user_id: str, password: str) -> None:
        super().__init__(page, user_id, password)
        self._popup: Page | None = None

    # ------------------------------------------------------------------
    # Login — CineQ may allow guest booking, but we try login if creds exist
    # ------------------------------------------------------------------

    async def login(self) -> bool | bytes:
        if not self.user_id:
            # No credentials — proceed as guest
            return True

        await self.page.goto(f"{BASE_URL}/Member/Login", wait_until="networkidle", timeout=20000)
        await self.page.wait_for_timeout(1000)

        # Fill login form
        id_input = await self.page.query_selector('input[name="UserId"], input[type="text"][id*="id" i]')
        pw_input = await self.page.query_selector('input[type="password"]')

        if not id_input or not pw_input:
            logger.warning("CineQ login form not found, proceeding as guest")
            return True

        await id_input.fill(self.user_id)
        await pw_input.fill(self.password)
        await self.page.keyboard.press("Enter")
        await self.page.wait_for_timeout(2000)

        # Check if login succeeded
        still_login = await self.page.query_selector('input[type="password"]')
        if still_login:
            logger.warning("CineQ login failed")
            return False

        return True

    # ------------------------------------------------------------------
    # Navigate to showtime → triggers reservation popup
    # ------------------------------------------------------------------

    async def navigate_to_showtime(
        self,
        theater_id: str,
        movie_id: str,
        showtime: str,
        play_date: str,
    ) -> bool:
        # First go to the theater schedule page
        url = f"{THEATER_URL}?TheaterCode={theater_id}"
        await self.page.goto(url, wait_until="networkidle", timeout=20000)
        await self.page.wait_for_timeout(2000)

        # Find the time slot that matches and click it to trigger simpleReserv
        # The time divs have data attributes we can use
        time_divs = await self.page.query_selector_all("div.time")
        for div in time_divs:
            data_code = await div.get_attribute("data-moviecode")
            data_time = await div.get_attribute("data-playnumber")
            text = await div.inner_text()

            if showtime in text:
                # Check if this is our movie by matching moviecode
                if data_code and movie_id and data_code != movie_id:
                    continue

                # Click and wait for popup
                async with self.page.expect_popup() as popup_info:
                    await div.click()
                self._popup = await popup_info.value
                await self._popup.wait_for_load_state("networkidle")
                await self._popup.wait_for_timeout(2000)
                return True

        # Fallback: trigger reservation via JS
        try:
            async with self.page.expect_popup() as popup_info:
                await self.page.evaluate(
                    f"$.desktop.reserve.open({{playDate: '{play_date}', theaterCode: '{theater_id}'}})"
                )
            self._popup = await popup_info.value
            await self._popup.wait_for_load_state("networkidle")
            await self._popup.wait_for_timeout(2000)
            return True
        except Exception:
            logger.exception("Failed to open CineQ reservation popup")
            return False

    # ------------------------------------------------------------------
    # Seat map
    # ------------------------------------------------------------------

    async def get_seat_map_screenshot(self) -> bytes:
        target = self._popup or self.page
        await target.wait_for_timeout(1000)

        # Try to find the seat map area
        seat_area = await target.query_selector(
            '[class*="seat"], [id*="seat"], .screen-wrap, .reserve-seat'
        )
        if seat_area:
            return await seat_area.screenshot()
        return await target.screenshot(full_page=False)

    async def select_seats(self, seats: list[str]) -> bool:
        target = self._popup or self.page

        for seat in seats:
            # Parse seat like "F7" → row F, col 7
            row_match = seat[0] if seat else ""
            col_match = seat[1:] if len(seat) > 1 else ""

            # Try multiple selector strategies
            selectors = [
                f'[data-seat="{seat}"]',
                f'[data-row="{row_match}"][data-col="{col_match}"]',
                f'[title="{seat}"]',
                f'[aria-label*="{seat}"]',
                f'.seat:has-text("{seat}")',
            ]

            clicked = False
            for sel in selectors:
                el = await target.query_selector(sel)
                if el:
                    await el.click()
                    clicked = True
                    break

            if not clicked:
                logger.warning("Could not find seat %s", seat)
                return False

            await target.wait_for_timeout(300)

        # Click the "선택 완료" or "다음" button
        next_btn = await target.query_selector(
            'button:has-text("선택"), a:has-text("다음"), button:has-text("결제")'
        )
        if next_btn:
            await next_btn.click()
            await target.wait_for_timeout(2000)

        return True

    # ------------------------------------------------------------------
    # Payment
    # ------------------------------------------------------------------

    async def get_payment_methods(self) -> list[str]:
        target = self._popup or self.page
        methods = []

        # Look for payment method buttons/tabs
        pay_elements = await target.query_selector_all(
            '[class*="pay"] li, [class*="payment"] button, .pay-method a'
        )
        for el in pay_elements:
            text = (await el.inner_text()).strip()
            if text and len(text) < 30:
                methods.append(text)

        if not methods:
            # Common Korean payment methods as fallback
            methods = ["신용카드", "카카오페이", "네이버페이"]

        return methods

    async def start_payment(self, method: str) -> bool | bytes:
        target = self._popup or self.page

        # Click the matching payment method
        pay_elements = await target.query_selector_all(
            '[class*="pay"] li, [class*="payment"] button, .pay-method a'
        )
        for el in pay_elements:
            text = (await el.inner_text()).strip()
            if method in text:
                await el.click()
                break

        await target.wait_for_timeout(2000)

        # Click "결제하기" button
        pay_btn = await target.query_selector(
            'button:has-text("결제"), a:has-text("결제하기"), button:has-text("확인")'
        )
        if pay_btn:
            # Payment may open a PG popup
            try:
                async with target.expect_popup(timeout=5000) as pg_popup:
                    await pay_btn.click()
                pg_page = await pg_popup.value
                await pg_page.wait_for_load_state("networkidle")
                # Take screenshot of PG page for auth
                screenshot = await pg_page.screenshot()
                return screenshot
            except Exception:
                # No popup — payment might be inline
                await pay_btn.click()
                await target.wait_for_timeout(3000)

        # Check if we need auth (SMS code input visible)
        auth_input = await target.query_selector(
            'input[type="text"][placeholder*="인증"], input[name*="auth"]'
        )
        if auth_input:
            return await target.screenshot()

        # Check if payment succeeded
        success = await target.query_selector(
            ':has-text("완료"), :has-text("성공"), :has-text("예매번호")'
        )
        return bool(success)

    async def submit_auth_code(self, code: str) -> bool:
        target = self._popup or self.page

        auth_input = await target.query_selector(
            'input[type="text"][placeholder*="인증"], input[name*="auth"], input[type="tel"]'
        )
        if auth_input:
            await auth_input.fill(code)

        confirm_btn = await target.query_selector(
            'button:has-text("확인"), button:has-text("인증")'
        )
        if confirm_btn:
            await confirm_btn.click()

        await target.wait_for_timeout(3000)

        success = await target.query_selector(
            ':has-text("완료"), :has-text("성공"), :has-text("예매번호")'
        )
        return bool(success)

    # ------------------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------------------

    async def get_confirmation_screenshot(self) -> bytes:
        target = self._popup or self.page
        return await target.screenshot(full_page=False)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup(self) -> None:
        if self._popup:
            try:
                await self._popup.close()
            except Exception:
                pass
        await super().cleanup()
