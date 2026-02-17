"""MegaBox booking session via Playwright."""

import logging

from playwright.async_api import Page

from cinepyle.booking.base import BookingSession

logger = logging.getLogger(__name__)

BASE_URL = "https://www.megabox.co.kr"
LOGIN_URL = f"{BASE_URL}/member/login"
BOOKING_URL = f"{BASE_URL}/booking"


class MegaBoxBookingSession(BookingSession):
    chain_name = "메가박스"

    def __init__(self, page: Page, user_id: str, password: str) -> None:
        super().__init__(page, user_id, password)

    async def login(self) -> bool | bytes:
        await self.page.goto(LOGIN_URL, wait_until="networkidle", timeout=20000)
        await self.page.wait_for_timeout(1000)

        id_input = await self.page.query_selector('#ibxLoginId, input[name="loginId"]')
        pw_input = await self.page.query_selector('#ibxLoginPwd, input[name="loginPwd"]')

        if not id_input or not pw_input:
            logger.warning("MegaBox login form not found")
            return False

        await id_input.fill(self.user_id)
        await pw_input.fill(self.password)

        login_btn = await self.page.query_selector(
            'button.btn-login, button:has-text("로그인"), .login-btn'
        )
        if login_btn:
            await login_btn.click()
        else:
            await self.page.keyboard.press("Enter")

        await self.page.wait_for_timeout(3000)

        # Check result — successful login redirects away from login page
        if "/member/login" in self.page.url:
            return False
        return True

    async def navigate_to_showtime(
        self,
        theater_id: str,
        movie_id: str,
        showtime: str,
        play_date: str,
    ) -> bool:
        url = f"{BOOKING_URL}?brchNo={theater_id}&playDe={play_date}"
        await self.page.goto(url, wait_until="networkidle", timeout=20000)
        await self.page.wait_for_timeout(3000)

        # Click the movie
        movie_els = await self.page.query_selector_all('.movie-list li, [data-movie-no]')
        for el in movie_els:
            text = await el.inner_text()
            movie_no = await el.get_attribute("data-movie-no") or ""
            if movie_id in text or movie_id == movie_no:
                await el.click()
                await self.page.wait_for_timeout(1000)
                break

        # Click the showtime
        time_els = await self.page.query_selector_all('.time-list a, [data-start-time]')
        for el in time_els:
            text = await el.inner_text()
            if showtime in text:
                await el.click()
                await self.page.wait_for_timeout(3000)
                return True

        # Fallback: just navigate to booking and hope we can select there
        return True

    async def get_seat_map_screenshot(self) -> bytes:
        await self.page.wait_for_timeout(1000)
        seat_area = await self.page.query_selector(
            '.seat-map, #seatMap, [class*="seat-wrap"], .screen-area'
        )
        if seat_area:
            return await seat_area.screenshot()
        return await self.page.screenshot(full_page=False)

    async def select_seats(self, seats: list[str]) -> bool:
        for seat in seats:
            row = seat[0] if seat else ""
            col = seat[1:] if len(seat) > 1 else ""

            selectors = [
                f'[data-seat-nm="{seat}"]',
                f'[data-seat-row="{row}"][data-seat-col="{col}"]',
                f'[title="{seat}"]',
                f'.seat-item:has-text("{seat}")',
            ]

            clicked = False
            for sel in selectors:
                el = await self.page.query_selector(sel)
                if el:
                    await el.click()
                    clicked = True
                    break

            if not clicked:
                logger.warning("MegaBox: could not find seat %s", seat)
                return False
            await self.page.wait_for_timeout(300)

        # Proceed to payment
        next_btn = await self.page.query_selector(
            'button:has-text("선택완료"), a:has-text("결제"), button.btn-next'
        )
        if next_btn:
            await next_btn.click()
            await self.page.wait_for_timeout(2000)

        return True

    async def get_payment_methods(self) -> list[str]:
        methods = []
        pay_elements = await self.page.query_selector_all(
            '.pay-list li, .payment-type button, [class*="pay-method"] a'
        )
        for el in pay_elements:
            text = (await el.inner_text()).strip()
            if text and len(text) < 30:
                methods.append(text)

        if not methods:
            methods = ["신용카드", "카카오페이", "네이버페이", "페이코"]
        return methods

    async def start_payment(self, method: str) -> bool | bytes:
        # Click payment method
        pay_elements = await self.page.query_selector_all(
            '.pay-list li, .payment-type button, [class*="pay-method"] a'
        )
        for el in pay_elements:
            text = (await el.inner_text()).strip()
            if method in text:
                await el.click()
                break

        await self.page.wait_for_timeout(1000)

        # Agree to terms if present
        agree_checkboxes = await self.page.query_selector_all(
            'input[type="checkbox"][name*="agree"], .agree-check input'
        )
        for cb in agree_checkboxes:
            is_checked = await cb.is_checked()
            if not is_checked:
                await cb.click()

        await self.page.wait_for_timeout(500)

        # Click final pay button
        pay_btn = await self.page.query_selector(
            'button:has-text("결제하기"), button:has-text("결제"), .btn-pay'
        )
        if pay_btn:
            try:
                async with self.page.expect_popup(timeout=5000) as pg_popup:
                    await pay_btn.click()
                pg_page = await pg_popup.value
                await pg_page.wait_for_load_state("networkidle")
                return await pg_page.screenshot()
            except Exception:
                await pay_btn.click()
                await self.page.wait_for_timeout(3000)

        auth_input = await self.page.query_selector(
            'input[placeholder*="인증"], input[name*="auth"]'
        )
        if auth_input:
            return await self.page.screenshot()

        success = await self.page.query_selector(
            ':has-text("예매완료"), :has-text("예매번호")'
        )
        return bool(success)

    async def submit_auth_code(self, code: str) -> bool:
        auth_input = await self.page.query_selector(
            'input[placeholder*="인증"], input[name*="auth"], input[type="tel"]'
        )
        if auth_input:
            await auth_input.fill(code)

        confirm_btn = await self.page.query_selector(
            'button:has-text("확인"), button:has-text("인증")'
        )
        if confirm_btn:
            await confirm_btn.click()

        await self.page.wait_for_timeout(3000)
        success = await self.page.query_selector(
            ':has-text("예매완료"), :has-text("예매번호")'
        )
        return bool(success)

    async def get_confirmation_screenshot(self) -> bytes:
        return await self.page.screenshot(full_page=False)
