"""LLM-based intent classification for natural language Telegram messages.

Classifies user messages into intents using the configured LLM provider,
with a keyword-based fallback when LLM is unavailable.
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class Intent(Enum):
    RANKING = "ranking"
    NEARBY = "nearby"
    THEATER_INFO = "theater_info"
    THEATER_LIST = "theater_list"
    NEW_MOVIES = "new_movies"
    DIGEST = "digest"
    BOOK = "book"
    SHOWTIME = "showtime"
    MOVIE_INFO = "movie_info"
    PREFERENCE = "preference"
    BOOKING_HISTORY = "booking_history"
    CHAT = "chat"


@dataclass
class ClassificationResult:
    intent: Intent
    reply: str  # LLM-generated response text
    params: dict = field(default_factory=dict)  # Extra params (e.g. theater name, chain)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

INTENT_SYSTEM_PROMPT = """\
당신은 한국 영화 알림봇의 어시스턴트입니다. 사용자의 메시지를 분석하여 의도를 파악하세요.

가능한 의도:
- "ranking": 박스오피스 순위, 영화 순위, 인기 영화 등을 물어볼 때
- "nearby": 근처/가까운 영화관을 찾고 싶어할 때
- "theater_info": 특정 영화관의 정보(상영관, IMAX, 좌석수 등)를 물어볼 때
- "theater_list": 특정 체인이나 지역의 극장 목록을 물어볼 때
- "new_movies": 새 영화, 최근 개봉작, 신작 정보를 물어볼 때
- "digest": 오늘의 영화 뉴스, 영화 소식, 다이제스트를 요청할 때
- "book": 영화 예매 링크를 원할 때 (시간/지역/상영시간 언급 없이 단순 예매 링크 요청)
- "showtime": 특정 지역/극장/시간에 상영 중인 영화나 상영시간을 물어볼 때. 예: "저녁 7시에 분당에 가는데 영화 뭐해?", "내일 용산에서 휴민트 상영시간", "CGV강남 오늘 뭐해?"
- "movie_info": 특정 영화의 정보(감독, 출연진, 장르, 러닝타임 등)를 물어볼 때. 예: "영화 휴민트에 누가 나와?", "파묘 감독 누구야?"
- "preference": 선호 극장이나 상영관 타입을 설정/변경/확인할 때. 예: "선호 극장 CGV용산 추가해줘", "IMAX만 보여줘", "내 선호 극장 뭐야?"
- "booking_history": 예매 내역, 예매 기록, 관람 기록, 과거에 본 영화를 확인하고 싶을 때. 예: "예매 내역 보여줘", "작년에 봤던 영화", "CGV 관람 기록"
- "chat": 그 외 일반 대화, 인사, 질문 등

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{
  "intent": "...",
  "reply": "사용자에게 보낼 한국어 응답",
  "params": {}
}

규칙:
- intent가 "ranking"이면 reply는 짧은 안내 메시지
- intent가 "nearby"이면 reply는 위치 전송을 요청하는 안내 메시지
- intent가 "theater_info"이면 params에 {"query": "사용자가 찾는 극장명 키워드"} 포함
- intent가 "theater_list"이면 params에 {"chain": "체인명 또는 빈 문자열", "region": "지역명 또는 빈 문자열"} 포함. 체인명은 CGV, 롯데시네마, 메가박스, 씨네Q, 독립영화관 중 하나
- intent가 "book"이면 params에 {"movie": "영화 제목 또는 빈 문자열", "chain": "체인명 또는 빈 문자열"} 포함. 포인트/쿠폰 언급 시 reply에 안내 포함
- intent가 "showtime"이면 params에 {"region": "지역명 또는 빈 문자열", "time": "시간 또는 빈 문자열", "date": "날짜(오늘/내일/YYYY-MM-DD) 또는 빈 문자열", "movie": "영화 제목 또는 빈 문자열", "theater": "구체적 극장명 또는 빈 문자열"} 포함
- intent가 "movie_info"이면 params에 {"movie": "영화 제목"} 포함
- intent가 "preference"이면 params에 {"action": "add|remove|list", "theater": "극장명 또는 빈 문자열", "screen_type": "상영관 타입 또는 빈 문자열"} 포함
- intent가 "booking_history"이면 params에 {"chain": "체인명 또는 빈 문자열"} 포함
- intent가 "new_movies"이면 reply는 짧은 안내 메시지
- intent가 "digest"이면 reply는 짧은 안내 메시지
- intent가 "chat"이면 reply에 친절하고 자연스러운 한국어 대화 응답을 작성
- "showtime" vs "book" 구분: 시간/지역/상영시간표 언급이 있으면 showtime, 단순 예매 링크 요청만이면 book
- "movie_info" vs "chat" 구분: 특정 영화의 감독/출연진/러닝타임/장르를 물어보면 movie_info
- "booking_history" vs "book" 구분: 예매 내역/기록/과거 확인 = booking_history, 지금 예매하고 싶다 = book
- 영화 관련 질문이지만 위 intent에 해당하지 않으면 chat으로 분류"""


# ---------------------------------------------------------------------------
# LLM classification
# ---------------------------------------------------------------------------


def classify_intent(
    user_message: str, provider_name: str, api_key: str
) -> ClassificationResult:
    """Classify user intent using the configured LLM provider.

    Uses the same provider/model conventions as digest/llm.py.
    Raises on API errors — caller should catch and use fallback.
    """
    if provider_name == "openai":
        import openai

        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=256,
        )
        raw = response.choices[0].message.content or "{}"

    elif provider_name == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=256,
            system=INTENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text

    elif provider_name == "google":
        from google import genai

        client = genai.Client(api_key=api_key)
        prompt = f"{INTENT_SYSTEM_PROMPT}\n\n{user_message}"
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        raw = response.text or "{}"

    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")

    return _parse_classification(raw)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_classification(raw: str) -> ClassificationResult:
    """Parse LLM JSON response into ClassificationResult."""
    text = raw.strip()
    # Strip markdown code fences (same pattern as digest/llm.py)
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    data = json.loads(text)

    intent_str = data.get("intent", "chat")
    try:
        intent = Intent(intent_str)
    except ValueError:
        intent = Intent.CHAT

    reply = data.get("reply", "")
    params = data.get("params", {})
    return ClassificationResult(intent=intent, reply=reply, params=params)


# ---------------------------------------------------------------------------
# Keyword fallback
# ---------------------------------------------------------------------------

_RANKING_KEYWORDS = ["순위", "박스오피스", "랭킹", "흥행", "차트"]
_NEARBY_KEYWORDS = ["근처", "가까운", "주변", "영화관 찾"]
_NEW_MOVIES_KEYWORDS = ["신작", "새 영화", "개봉", "최근 영화", "새로 나온"]
_DIGEST_KEYWORDS = ["뉴스", "소식", "다이제스트", "기사"]
_THEATER_LIST_KEYWORDS = ["극장 목록", "극장 리스트", "영화관 목록", "영화관 리스트"]
_BOOKING_HISTORY_KEYWORDS = ["예매 내역", "예매내역", "예매 기록", "관람 기록", "예매 조회", "예매 확인", "봤던 영화", "관람기록", "예매기록"]
_BOOK_KEYWORDS = ["예매", "예약", "티켓", "표 사", "표 끊", "booking", "book"]
_SHOWTIME_KEYWORDS = ["상영시간", "시간표", "몇시", "뭐해", "뭐하", "상영 중"]
_SHOWTIME_TIME_SIGNALS = ["시에", "시 ", "오전", "오후", "저녁", "아침", "밤"]
_MOVIE_INFO_KEYWORDS = ["누가 나와", "출연", "감독", "러닝타임", "줄거리", "장르", "영화 정보", "누가 나오"]
_PREFERENCE_KEYWORDS = ["선호 극장", "선호극장", "자주 가는", "즐겨찾기", "선호 상영관"]

# Chain name detection for theater_list fallback
_CHAIN_KEYWORDS = {
    "cgv": "CGV",
    "씨지브이": "CGV",
    "롯데시네마": "롯데시네마",
    "롯데": "롯데시네마",
    "메가박스": "메가박스",
    "씨네q": "씨네Q",
    "독립영화관": "독립영화관",
    "독립": "독립영화관",
    "예술영화관": "독립영화관",
}

# Theater info keywords — specific theater queries
_THEATER_INFO_KEYWORDS = ["상영관", "스크린", "imax", "아이맥스", "4dx", "돌비", "좌석"]


def _parse_showtime_params(text: str) -> dict:
    """Extract region, time, date, movie, theater from a showtime query."""
    import re

    msg = text.strip()
    region = ""
    time_str = ""
    date_str = ""
    movie = ""
    theater = ""

    # --- Date extraction ---
    if "내일모레" in msg or "모레" in msg:
        date_str = "모레"
    elif "내일" in msg:
        date_str = "내일"
    elif "오늘" in msg:
        date_str = "오늘"
    else:
        m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", msg)
        if m:
            date_str = m.group(0)

    # --- Time extraction ---
    # "저녁 7시", "오후 3시 30분", "19시", "7시반", etc.
    m = re.search(
        r"(오전|오후|저녁|아침|밤|낮)?\s*(\d{1,2})\s*시\s*(반|(\d{1,2})\s*분)?",
        msg,
    )
    if m:
        period = m.group(1) or ""
        hour = int(m.group(2))
        if m.group(3) == "반":
            minute = 30
        elif m.group(4):
            minute = int(m.group(4))
        else:
            minute = 0
        if period in ("오후", "저녁", "밤") and hour < 12:
            hour += 12
        time_str = f"{hour}시{f' {minute}분' if minute else ''}"

    # --- Theater / chain detection ---
    # Match known chain+theater patterns like "CGV용산", "메가박스 코엑스"
    chain_theater_match = re.search(
        r"(CGV|씨지브이|롯데시네마|롯데|메가박스)\s*(\S+)?",
        msg,
        re.IGNORECASE,
    )
    if chain_theater_match:
        full = chain_theater_match.group(0).strip()
        # Remove trailing particles (에, 에서, 의, 은, 는, 이, 가, 을, 를)
        theater = re.sub(r"[에서의은는이가을를]+$", "", full)

    # --- Region extraction ---
    # Common Korean region/district names
    _REGIONS = [
        "강남", "강북", "강서", "강동", "서초", "송파", "잠실", "영등포",
        "마포", "홍대", "신촌", "종로", "명동", "용산", "여의도",
        "분당", "판교", "일산", "수원", "인천", "부산", "대구", "광주",
        "대전", "울산", "제주", "성남", "안양", "부천", "고양", "청주",
        "천안", "전주", "포항", "창원", "김해", "구리", "하남", "광명",
        "동탄", "세종", "김포", "양산", "거제", "통영", "속초", "춘천",
        "원주", "경주", "목포", "순천", "여수", "익산", "군산", "서산",
        "평택", "오산", "이천", "양주", "의정부", "파주", "노원", "왕십리",
        "건대", "성수", "합정", "상암", "목동", "구로", "신도림", "가산",
        "코엑스", "월드몰", "아이파크몰",
    ]
    for r in _REGIONS:
        if r in msg:
            region = r
            # If no explicit theater was found, use chain + region as theater query
            if not theater:
                theater = r
            break

    return {
        "region": region,
        "time": time_str,
        "date": date_str,
        "movie": movie,
        "theater": theater,
    }


def classify_intent_fallback(user_message: str) -> ClassificationResult:
    """Keyword-based intent classification when LLM is unavailable."""
    msg = user_message.lower().strip()

    # Preference (check early — very specific keywords)
    has_preference = any(kw in msg for kw in _PREFERENCE_KEYWORDS)
    # Also check for "선호" + action pattern
    if not has_preference and "선호" in msg:
        has_preference = True
    if has_preference:
        action = "list"
        if "추가" in msg or "설정" in msg or "등록" in msg:
            action = "add"
        elif "삭제" in msg or "제거" in msg or "빼" in msg:
            action = "remove"
        return ClassificationResult(
            intent=Intent.PREFERENCE,
            reply="선호 설정을 확인할게요!",
            params={"action": action, "theater": "", "screen_type": ""},
        )

    # Movie info (check before showtime — specific patterns)
    for kw in _MOVIE_INFO_KEYWORDS:
        if kw in msg:
            return ClassificationResult(
                intent=Intent.MOVIE_INFO,
                reply="영화 정보를 검색할게요!",
                params={"movie": user_message},
            )

    # Showtime (check before booking — has time/location signals)
    has_showtime_kw = any(kw in msg for kw in _SHOWTIME_KEYWORDS)
    has_time_signal = any(kw in msg for kw in _SHOWTIME_TIME_SIGNALS)
    if has_showtime_kw or has_time_signal:
        params = _parse_showtime_params(user_message)
        return ClassificationResult(
            intent=Intent.SHOWTIME,
            reply="상영시간을 조회할게요!",
            params=params,
        )

    # Theater info (specific theater query — check before theater_list)
    for kw in _THEATER_INFO_KEYWORDS:
        if kw in msg:
            return ClassificationResult(
                intent=Intent.THEATER_INFO,
                reply="극장 정보를 조회할게요!",
                params={"query": user_message},
            )

    # Theater list (chain/region query)
    for kw in _THEATER_LIST_KEYWORDS:
        if kw in msg:
            chain = ""
            for ck, cv in _CHAIN_KEYWORDS.items():
                if ck in msg:
                    chain = cv
                    break
            return ClassificationResult(
                intent=Intent.THEATER_LIST,
                reply="극장 목록을 조회할게요!",
                params={"chain": chain, "region": ""},
            )

    # Check for chain name + "극장" / "영화관" pattern
    for ck, cv in _CHAIN_KEYWORDS.items():
        if ck in msg and ("극장" in msg or "영화관" in msg or "목록" in msg):
            return ClassificationResult(
                intent=Intent.THEATER_LIST,
                reply=f"{cv} 극장 목록을 조회할게요!",
                params={"chain": cv, "region": ""},
            )

    # Booking history (check BEFORE booking — "예매 내역" vs "예매")
    for kw in _BOOKING_HISTORY_KEYWORDS:
        if kw in msg:
            chain = ""
            for ck, cv in _CHAIN_KEYWORDS.items():
                if ck in msg and cv in ("CGV", "롯데시네마", "메가박스"):
                    chain = cv
                    break
            return ClassificationResult(
                intent=Intent.BOOKING_HISTORY,
                reply="예매 내역을 조회할게요!",
                params={"chain": chain},
            )

    # Booking
    for kw in _BOOK_KEYWORDS:
        if kw in msg:
            chain = ""
            for ck, cv in _CHAIN_KEYWORDS.items():
                if ck in msg and cv in ("CGV", "롯데시네마", "메가박스"):
                    chain = cv
                    break
            return ClassificationResult(
                intent=Intent.BOOK,
                reply="예매 링크를 준비할게요! 🎫",
                params={"movie": "", "chain": chain},
            )

    for kw in _RANKING_KEYWORDS:
        if kw in msg:
            return ClassificationResult(
                intent=Intent.RANKING,
                reply="박스오피스 순위를 가져올게요!",
            )

    for kw in _NEARBY_KEYWORDS:
        if kw in msg:
            return ClassificationResult(
                intent=Intent.NEARBY,
                reply="근처 영화관을 찾아드릴게요! 위치를 전송해주세요.",
            )

    for kw in _NEW_MOVIES_KEYWORDS:
        if kw in msg:
            return ClassificationResult(
                intent=Intent.NEW_MOVIES,
                reply="최근 개봉작을 확인할게요!",
            )

    for kw in _DIGEST_KEYWORDS:
        if kw in msg:
            return ClassificationResult(
                intent=Intent.DIGEST,
                reply="영화 소식을 가져올게요!",
            )

    return ClassificationResult(
        intent=Intent.CHAT,
        reply=(
            "안녕하세요! 저는 영화 알림봇이에요 🎬\n\n"
            "이런 것들을 물어보실 수 있어요:\n"
            "• 저녁 7시 분당 영화 뭐해?\n"
            "• 영화 파묘에 누가 나와?\n"
            "• 박스오피스 순위 보여줘\n"
            "• 근처 영화관 찾아줘\n"
            "• CGV 예매하고 싶어\n"
            "• 선호 극장 CGV용산 추가해줘"
        ),
    )
