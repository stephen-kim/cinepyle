"""Lotte Cinema booking session via Playwright."""

import logging

from playwright.async_api import Page

from cinepyle.booking.base import BookingSession

logger = logging.getLogger(__name__)

BASE_URL = "https://www.lottecinema.co.kr"
LOGIN_URL = f"{BASE_URL}/NLCHS/member/login"
TICKETING_URL = f"{BASE_URL}/NLCHS/Ticketing"


class LotteBookingSession(BookingSession):
    chain_name = "롯데시네마"

    def __init__(self, page: Page, user_id: str, password: str) -> None:
        super().__init__(page, user_id, password)

    async def login(self) -> bool | bytes:
        await self.page.goto(LOGIN_URL, wait_until="networkidle", timeout=20000)
        await self.page.wait_for_timeout(1000)

        id_input = await self.page.query_selector(
            '#txtLoginID, input[name="loginId"], input[type="text"][id*="login" i]'
        )
        pw_input = await self.page.query_selector(
            '#txtLoginPW, input[name="loginPw"], input[type="password"]'
        )

        if not id_input or not pw_input:
            logger.warning("Lotte Cinema login form not found")
            return False

        await id_input.fill(self.user_id)
        await pw_input.fill(self.password)

        login_btn = await self.page.query_selector(
            'button:has-text("로그인"), .btn-login, a:has-text("로그인")'
        )
        if login_btn:
            await login_btn.click()
        else:
            await self.page.keyboard.press("Enter")

        await self.page.wait_for_timeout(3000)

        # Check: still on login page?
        pw_still = await self.page.query_selector('input[type="password"]')
        if pw_still and "/login" in self.page.url:
            return False
        return True

    async def navigate_to_showtime(
        self,
        theater_id: str,
        movie_id: str,
        showtime: str,
        play_date: str,
    ) -> bool:
        # Lotte ticketing page with theater filter
        url = f"{TICKETING_URL}?cinemaID={theater_id}"
        await self.page.goto(url, wait_until="networkidle", timeout=20000)
        await self.page.wait_for_timeout(3000)

        # Select movie from the list
        movie_els = await self.page.query_selector_all(
            '.movie_list li, .lst_movie li, [data-movie-code]'
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
            '.time_list a, .lst_time a, [data-start-time]'
        )
        for el in time_els:
            text = await el.inner_text()
            if showtime in text:
                await el.click()
                await self.page.wait_for_timeout(3000)
                return True

        return True

    async def get_seat_map_screenshot(self) -> bytes:
        await self.page.wait_for_timeout(1000)
        seat_area = await self.page.query_selector(
            '.seat_map, #divSeatMap, [class*="seat"], .screen_wrap'
        )
        if seat_area:
            return await seat_area.screenshot()
        return await self.page.screenshot(full_page=False)

    async def select_seats(self, seats: list[str]) -> bool:
        for seat in seats:
            row = seat[0] if seat else ""
            col = seat[1:] if len(seat) > 1 else ""

            selectors = [
                f'[data-seat-name="{seat}"]',
                f'[data-row="{row}"][data-no="{col}"]',
                f'[title="{seat}"]',
                f'a:has-text("{seat}")',
            ]

            clicked = False
            for sel in selectors:
                el = await self.page.query_selector(sel)
                if el:
                    await el.click()
                    clicked = True
                    break

            if not clicked:
                logger.warning("Lotte: could not find seat %s", seat)
                return False
            await self.page.wait_for_timeout(300)

        next_btn = await self.page.query_selector(
            'button:has-text("선택완료"), a:has-text("결제"), .btn_next'
        )
        if next_btn:
            await next_btn.click()
            await self.page.wait_for_timeout(2000)

        return True

    async def get_payment_methods(self) -> list[str]:
        methods = []
        pay_elements = await self.page.query_selector_all(
            '.pay_list li, .lst_pay li, [class*="payment"] button'
        )
        for el in pay_elements:
            text = (await el.inner_text()).strip()
            if text and len(text) < 30:
                methods.append(text)

        if not methods:
            methods = ["신용카드", "카카오페이", "네이버페이", "L.PAY"]
        return methods

    async def start_payment(self, method: str) -> bool | bytes:
        pay_elements = await self.page.query_selector_all(
            '.pay_list li, .lst_pay li, [class*="payment"] button'
        )
        for el in pay_elements:
            text = (await el.inner_text()).strip()
            if method in text:
                await el.click()
                break

        await self.page.wait_for_timeout(1000)

        # Agree to terms
        agree_boxes = await self.page.query_selector_all(
            'input[type="checkbox"][name*="agree"], .chk_agree input'
        )
        for cb in agree_boxes:
            if not await cb.is_checked():
                await cb.click()

        await self.page.wait_for_timeout(500)

        pay_btn = await self.page.query_selector(
            'button:has-text("결제하기"), a:has-text("결제"), .btn_pay'
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
