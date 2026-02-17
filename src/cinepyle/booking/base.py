"""Abstract base class for theater chain booking sessions.

Each chain implements this interface. A single Playwright Page is kept
alive throughout the booking flow so that login cookies and navigation
state are preserved.
"""

from abc import ABC, abstractmethod

from playwright.async_api import Page


class BookingSession(ABC):
    """Drives a headless browser through the booking flow of one theater chain."""

    chain_name: str = ""

    def __init__(self, page: Page, user_id: str, password: str) -> None:
        self.page = page
        self.user_id = user_id
        self.password = password

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    @abstractmethod
    async def login(self) -> bool | bytes:
        """Log in to the theater website.

        Returns:
            True  – login succeeded.
            bytes – CAPTCHA image that must be solved by the user.
                    Call submit_captcha() with the answer afterwards.
            False – login failed.
        """

    async def submit_captcha(self, answer: str) -> bool:
        """Submit a CAPTCHA answer. Only needed for chains that return
        an image from login(). Default raises NotImplementedError."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Booking navigation
    # ------------------------------------------------------------------

    @abstractmethod
    async def navigate_to_showtime(
        self,
        theater_id: str,
        movie_id: str,
        showtime: str,
        play_date: str,
    ) -> bool:
        """Navigate the browser to the seat-selection screen for the
        chosen theater / movie / showtime combination.

        Returns True if the seat map is ready to be captured.
        """

    # ------------------------------------------------------------------
    # Seat selection
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_seat_map_screenshot(self) -> bytes:
        """Return a PNG screenshot of the current seat map."""

    @abstractmethod
    async def select_seats(self, seats: list[str]) -> bool:
        """Click the requested seats (e.g. ['F7', 'F8']).

        Returns True if the seats were successfully selected.
        """

    # ------------------------------------------------------------------
    # Payment
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_payment_methods(self) -> list[str]:
        """Return names of available payment methods on screen."""

    @abstractmethod
    async def start_payment(self, method: str) -> bool | bytes:
        """Initiate payment with the chosen method.

        Returns:
            True  – payment completed (no extra auth needed).
            bytes – screenshot of an auth prompt (SMS code, app confirm, …).
            False – payment failed.
        """

    async def submit_auth_code(self, code: str) -> bool:
        """Submit an SMS / OTP / app-confirm code during payment.

        Returns True if the booking was confirmed.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_confirmation_screenshot(self) -> bytes:
        """Return a screenshot of the booking confirmation page."""

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup(self) -> None:
        """Close the Playwright page and release resources."""
        try:
            await self.page.close()
        except Exception:
            pass
