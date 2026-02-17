"""Booking conversation state management."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BookingPhase(str, Enum):
    """Tracks where we are in the booking pipeline."""

    IDLE = "idle"
    GATHERING_INFO = "gathering_info"
    LOGGING_IN = "logging_in"
    AWAITING_CAPTCHA = "awaiting_captcha"
    SELECTING_SEATS = "selecting_seats"
    CHOOSING_PAYMENT = "choosing_payment"
    AWAITING_AUTH = "awaiting_auth"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class BookingState:
    """All accumulated booking information for one user session."""

    phase: BookingPhase = BookingPhase.IDLE

    # Gathered entities (None = not yet provided)
    chain: str | None = None  # "cgv", "lotte", "megabox", "cineq"
    theater_name: str | None = None  # "용산아이파크몰"
    theater_id: str | None = None  # Resolved TheaterCode
    theater_region: str | None = None  # CGV-specific RegionCode
    movie_name: str | None = None  # "캡틴 아메리카"
    movie_id: str | None = None  # Resolved movie key from schedule
    showtime: str | None = None  # "19:00"
    play_date: str | None = None  # "20260217"
    seats: list[str] | None = None  # ["F7", "F8"]
    payment_method: str | None = None  # "신용카드"

    # User location (from Telegram location message)
    user_latitude: float | None = None
    user_longitude: float | None = None

    # Theater location (resolved from theater data)
    theater_latitude: float | None = None
    theater_longitude: float | None = None

    # Available options fetched from APIs
    available_theaters: list[dict] = field(default_factory=list)
    available_movies: dict = field(default_factory=dict)
    available_payment_methods: list[str] = field(default_factory=list)

    # Conversation history (bounded)
    messages: list[dict] = field(default_factory=list)

    # Active BookingSession flag
    session_active: bool = False

    def summary_for_llm(self) -> str:
        """Compact state summary injected into system prompt."""
        parts = []
        if self.user_latitude is not None and self.user_longitude is not None:
            parts.append(
                f"사용자 위치: ({self.user_latitude:.6f}, {self.user_longitude:.6f})"
            )
        if self.chain:
            chain_names = {
                "cgv": "CGV",
                "lotte": "롯데시네마",
                "megabox": "메가박스",
                "cineq": "씨네Q",
            }
            parts.append(f"체인: {chain_names.get(self.chain, self.chain)}")
        if self.theater_name:
            parts.append(f"극장: {self.theater_name}")
        if self.play_date:
            parts.append(f"날짜: {self.play_date}")
        if self.movie_name:
            parts.append(f"영화: {self.movie_name}")
        if self.showtime:
            parts.append(f"시간: {self.showtime}")
        if self.seats:
            parts.append(f"좌석: {', '.join(self.seats)}")
        if self.payment_method:
            parts.append(f"결제: {self.payment_method}")
        if not parts:
            return "아직 수집된 예매 정보가 없습니다."
        return "현재 수집된 정보:\n" + "\n".join(f"- {p}" for p in parts)

    def missing_fields(self) -> list[str]:
        """Return names of fields still needed before booking can proceed."""
        required = []
        if not self.chain:
            required.append("chain")
        if not self.theater_id:
            required.append("theater")
        if not self.movie_id:
            required.append("movie")
        if not self.showtime:
            required.append("showtime")
        return required

    def add_message(self, role: str, content: str, max_history: int = 10) -> None:
        """Append a message and trim old ones."""
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > max_history:
            self.messages = self.messages[-max_history:]

    def reset(self) -> None:
        """Reset to idle state.

        Note: user_latitude/user_longitude are preserved across resets
        so the user doesn't need to re-send their location.
        """
        self.phase = BookingPhase.IDLE
        self.chain = None
        self.theater_name = None
        self.theater_id = None
        self.theater_region = None
        self.theater_latitude = None
        self.theater_longitude = None
        self.movie_name = None
        self.movie_id = None
        self.showtime = None
        self.play_date = None
        self.seats = None
        self.payment_method = None
        self.available_theaters = []
        self.available_movies = {}
        self.available_payment_methods = []
        self.messages = []
        self.session_active = False
