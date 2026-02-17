"""CGV booking session via Playwright.

CGV uses CAPTCHA on login.  The flow sends the CAPTCHA image back to
the Telegram user, who types the answer.  The answer is then submitted
to complete login before proceeding to seat selection.
"""

import logging

from playwright.async_api import Page

from cinepyle.booking.base import BookingSession

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cgv.co.kr"
LOGIN_URL = f"{BASE_URL}/cnm/mbrAss/loginInput"
BOOKING_URL = f"{BASE_URL}/cnm/movieBook/cinema"


class CGVBookingSession(BookingSession):
    chain_name = "CGV"

    def __init__(self, page: Page, user_id: str, password: str) -> None:
        super().__init__(page, user_id, password)

    # ------------------------------------------------------------------
    # Login — CGV has CAPTCHA
    # ------------------------------------------------------------------

    async def login(self) -> bool | bytes:
        await self.page.goto(LOGIN_URL, wait_until="networkidle", timeout=20000)
        await self.page.wait_for_timeout(2000)

        # Fill ID/PW
        id_input = await self.page.query_selector(
            'input[name="userId"], input[id*="id" i][type="text"], #txtLoginID'
        )
        pw_input = await self.page.query_selector(
            'input[name="userPwd"], input[type="password"], #txtLoginPW'
        )

        if not id_input or not pw_input:
            logger.warning("CGV login form not found")
            return False

        await id_input.fill(self.user_id)
        await pw_input.fill(self.password)

        # Check for CAPTCHA
        captcha_img = await self.page.query_selector(
            'img[src*="captcha"], img[id*="captcha" i], '
            'img[alt*="보안"], [class*="captcha"] img'
        )

        if captcha_img:
            # Screenshot the CAPTCHA image and return it
            screenshot = await captcha_img.screenshot()
            return screenshot

        # No CAPTCHA — just click login
        login_btn = await self.page.query_selector(
            'button:has-text("로그인"), .btn-login, a:has-text("로그인")'
        )
        if login_btn:
            await login_btn.click()
        else:
            await self.page.keyboard.press("Enter")

        await self.page.wait_for_timeout(3000)

        # Check success
        if "login" in self.page.url.lower():
            return False
        return True

    async def submit_captcha(self, answer: str) -> bool:
        """Submit CAPTCHA answer and complete login."""
        captcha_input = await self.page.query_selector(
            'input[name*="captcha"], input[id*="captcha" i], '
            'input[placeholder*="보안"], input[placeholder*="문자"]'
        )

        if captcha_input:
            await captcha_input.fill(answer)

        # Click login button
        login_btn = await self.page.query_selector(
            'button:has-text("로그인"), .btn-login, a:has-text("로그인")'
        )
        if login_btn:
            await login_btn.click()
        else:
            await self.page.keyboard.press("Enter")

        await self.page.wait_for_timeout(3000)

        if "login" in self.page.url.lower():
            return False
        return True

    # ------------------------------------------------------------------
    # Navigate to showtime
    # ------------------------------------------------------------------

    async def navigate_to_showtime(
        self,
        theater_id: str,
        movie_id: str,
        showtime: str,
        play_date: str,
    ) -> bool:
        url = f"{BOOKING_URL}?theaterCode={theater_id}"
        await self.page.goto(url, wait_until="networkidle", timeout=20000)
        await self.page.wait_for_timeout(3000)

        # Select movie
        movie_els = await self.page.query_selector_all(
            '[class*="movie-list"] li, [data-movie-code], .movie-item'
        )
        for el in movie_els:
            text = await el.inner_text()
            code = await el.get_attribute("data-movie-code") or ""
            if movie_id in text or movie_id == code:
                await el.click()
                await self.page.wait_for_timeout(1000)
                break

        # Select showtime
        time_els = await self.page.query_selector_all(
            '[class*="time"] a, [data-start-time], .showtime-item'
        )
        for el in time_els:
            text = await el.inner_text()
            if showtime in text:
                await el.click()
                await self.page.wait_for_timeout(3000)
                return True

        return True

    # ------------------------------------------------------------------
    # Seat selection
    # ------------------------------------------------------------------

    async def get_seat_map_screenshot(self) -> bytes:
        await self.page.wait_for_timeout(2000)

        # CGV might use canvas or SVG for seat map
        seat_area = await self.page.query_selector(
            'canvas[id*="seat"], .seat-map, #seatContainer, '
            '[class*="seat-wrap"], svg[class*="seat"]'
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
                f'[data-row="{row}"][data-col="{col}"]',
                f'[title="{seat}"]',
                f'[aria-label*="{seat}"]',
                f'.seat:has-text("{seat}")',
            ]

            clicked = False
            for sel in selectors:
                el = await self.page.query_selector(sel)
                if el:
                    await el.click()
                    clicked = True
                    break

            if not clicked:
                logger.warning("CGV: could not find seat %s", seat)
                return False
            await self.page.wait_for_timeout(300)

        next_btn = await self.page.query_selector(
            'button:has-text("선택완료"), a:has-text("결제"), button.btn-next, '
            'button:has-text("다음")'
        )
        if next_btn:
            await next_btn.click()
            await self.page.wait_for_timeout(2000)

        return True

    # ------------------------------------------------------------------
    # Payment
    # ------------------------------------------------------------------

    async def get_payment_methods(self) -> list[str]:
        methods = []
        pay_elements = await self.page.query_selector_all(
            '.pay-type li, [class*="payment"] button, .pay-method-list a'
        )
        for el in pay_elements:
            text = (await el.inner_text()).strip()
            if text and len(text) < 30:
                methods.append(text)

        if not methods:
            methods = ["신용카드", "카카오페이", "네이버페이", "PAYCO"]
        return methods

    async def start_payment(self, method: str) -> bool | bytes:
        pay_elements = await self.page.query_selector_all(
            '.pay-type li, [class*="payment"] button, .pay-method-list a'
        )
        for el in pay_elements:
            text = (await el.inner_text()).strip()
            if method in text:
                await el.click()
                break

        await self.page.wait_for_timeout(1000)

        # Agree to terms
        agree_boxes = await self.page.query_selector_all(
            'input[type="checkbox"][name*="agree"], .agree-wrap input'
        )
        for cb in agree_boxes:
            if not await cb.is_checked():
                await cb.click()

        await self.page.wait_for_timeout(500)

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
            ':has-text("예매완료"), :has-text("예매번호"), :has-text("예매 완료")'
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
            ':has-text("예매완료"), :has-text("예매번호"), :has-text("예매 완료")'
        )
        return bool(success)

    async def get_confirmation_screenshot(self) -> bytes:
        return await self.page.screenshot(full_page=False)
