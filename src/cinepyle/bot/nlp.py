"""LLM-based intent classification for natural language Telegram messages.

Classifies user messages into intents using native function calling (tool use)
across OpenAI, Anthropic, and Google GenAI providers.
Falls back to keyword-based classification when no LLM is available.
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
    SEAT_MAP = "seat_map"
    CHAT = "chat"


@dataclass
class ClassificationResult:
    intent: Intent
    reply: str  # LLM-generated response text
    params: dict = field(default_factory=dict)  # Extra params (e.g. theater name, chain)


# ---------------------------------------------------------------------------
# Tool definitions (canonical, provider-agnostic)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "showtime",
        "description": "상영시간 조회. 사용자가 특정 지역, 시간, 날짜, 영화, 극장의 상영시간을 알고 싶을 때. 시간/지역/극장 언급이 있으면 book이 아니라 이것.",
        "parameters": {
            "reply": {"type": "string", "description": "친근한 한국어 안내 메시지 (반말, 이모지 포함)"},
            "region": {"type": "string", "description": "지역명 (강남, 분당, 송도, 부산 등). 반드시 추출할 것. 없으면 빈 문자열"},
            "time": {"type": "string", "description": "시간 (원문 그대로: '3시반', '19:00', '저녁 7시' 등). 반드시 추출할 것. 없으면 빈 문자열"},
            "date": {"type": "string", "description": "날짜 (원문 그대로: '내일', '모레', '2월 21일' 등). '내일', '오늘' 등 반드시 추출할 것. 없으면 빈 문자열"},
            "movie": {"type": "string", "description": "영화 제목만. 없으면 빈 문자열"},
            "theater": {"type": "string", "description": "구체적 극장명 (CGV용산 등). 없으면 빈 문자열"},
        },
        "required": ["reply"],
    },
    {
        "name": "ranking",
        "description": "박스오피스 순위, 인기 영화 차트 조회.",
        "parameters": {
            "reply": {"type": "string", "description": "친근한 한국어 안내 메시지"},
        },
        "required": ["reply"],
    },
    {
        "name": "nearby",
        "description": "근처/주변/가까운 영화관 찾기. '근처 영화관', '가까운 극장', '영화관 어디', '주변 CGV', '이근처 영화관', '여기 근처' 등. 위치 확인은 봇이 따로 처리하므로 이 도구를 호출하면 됨. '이근처', '여기근처', '이 근처' 등 대명사는 region이 아님 (빈 문자열로).",
        "parameters": {
            "reply": {"type": "string", "description": "위치 전송을 요청하는 안내 메시지"},
            "chain": {"type": "string", "description": "체인명 (CGV, 롯데시네마, 메가박스 등). 반드시 추출할 것. 없으면 빈 문자열"},
            "region": {"type": "string", "description": "구체적 지역명 (신림동, 강남, 분당 등). '이근처/여기/이쪽' 같은 대명사는 빈 문자열로. 없으면 빈 문자열"},
        },
        "required": ["reply"],
    },
    {
        "name": "theater_info",
        "description": "특정 극장의 상세 정보 (상영관 수, IMAX 여부, 좌석수 등).",
        "parameters": {
            "reply": {"type": "string", "description": "친근한 한국어 안내 메시지"},
            "query": {"type": "string", "description": "극장명 검색어"},
        },
        "required": ["reply", "query"],
    },
    {
        "name": "theater_list",
        "description": "체인별/지역별 극장 목록 조회.",
        "parameters": {
            "reply": {"type": "string", "description": "친근한 한국어 안내 메시지"},
            "chain": {"type": "string", "description": "CGV/롯데시네마/메가박스/씨네Q/독립영화관 중 하나. 없으면 빈 문자열"},
            "region": {"type": "string", "description": "지역명. 없으면 빈 문자열"},
        },
        "required": ["reply"],
    },
    {
        "name": "new_movies",
        "description": "최근 개봉작, 신작, 개봉 예정 영화 조회.",
        "parameters": {
            "reply": {"type": "string", "description": "친근한 한국어 안내 메시지"},
        },
        "required": ["reply"],
    },
    {
        "name": "digest",
        "description": "영화 뉴스, 소식, 다이제스트, 트렌드, 이슈, 기사, 업계 소식 조회. '뉴스 보여줘', '영화 소식', '다이제스트' 등.",
        "parameters": {
            "reply": {"type": "string", "description": "친근한 한국어 안내 메시지"},
        },
        "required": ["reply"],
    },
    {
        "name": "book",
        "description": "예매 링크 안내. 단순히 '예매하고 싶어'처럼 시간/지역/극장 없이 예매 의사만 표현할 때.",
        "parameters": {
            "reply": {"type": "string", "description": "친근한 한국어 안내 메시지"},
            "movie": {"type": "string", "description": "영화 제목. 없으면 빈 문자열"},
            "chain": {"type": "string", "description": "CGV/롯데시네마/메가박스 중 하나. 없으면 빈 문자열"},
        },
        "required": ["reply"],
    },
    {
        "name": "movie_info",
        "description": "영화 정보 조회 (감독, 출연진, 장르, 러닝타임 등).",
        "parameters": {
            "reply": {"type": "string", "description": "친근한 한국어 안내 메시지"},
            "movie": {"type": "string", "description": "영화 제목만 (조사/접미사 제거). '영화 파묘에 누가 나와?' → '파묘'"},
        },
        "required": ["reply", "movie"],
    },
    {
        "name": "preference",
        "description": "선호 극장/상영관 관리 (추가, 삭제, 확인).",
        "parameters": {
            "reply": {"type": "string", "description": "친근한 한국어 안내 메시지"},
            "action": {"type": "string", "enum": ["add", "remove", "list"], "description": "add=추가/설정, remove=삭제/제거, list=확인/조회"},
            "theater": {"type": "string", "description": "극장명. 없으면 빈 문자열"},
            "screen_type": {"type": "string", "description": "상영관 타입 (IMAX, 4DX 등). 없으면 빈 문자열"},
        },
        "required": ["reply", "action"],
    },
    {
        "name": "booking_history",
        "description": "예매 내역/기록/확인 조회. '예매하고 싶다'는 book, '예매 내역 확인'은 이것.",
        "parameters": {
            "reply": {"type": "string", "description": "친근한 한국어 안내 메시지"},
            "chain": {"type": "string", "description": "CGV/롯데시네마/메가박스 중 하나. 없으면 빈 문자열(전체)"},
        },
        "required": ["reply"],
    },
    {
        "name": "seat_map",
        "description": "좌석 배치도/좌석도 보기. 특정 상영 회차의 좌석 현황 이미지. '좌석 보여줘', '자리 보여줘', '좌석 배치도', '어디 남았어' 등.",
        "parameters": {
            "reply": {"type": "string", "description": "친근한 한국어 안내 메시지"},
            "region": {"type": "string", "description": "지역명. 없으면 빈 문자열"},
            "theater": {"type": "string", "description": "극장명. 없으면 빈 문자열"},
            "movie": {"type": "string", "description": "영화 제목. 없으면 빈 문자열"},
            "time": {"type": "string", "description": "시간. 없으면 빈 문자열"},
            "date": {"type": "string", "description": "날짜. 없으면 빈 문자열"},
        },
        "required": ["reply"],
    },
]


# ---------------------------------------------------------------------------
# System prompt (simplified — tool schemas describe intents)
# ---------------------------------------------------------------------------

TOOL_SYSTEM_PROMPT = """\
당신은 한국 영화 알림봇 "Cinepyle"의 어시스턴트입니다.
사용자의 메시지를 분석하여 적절한 도구(function)를 호출하세요.
반말로 대화하되 친근하게 말해주세요. 이모지를 적절히 사용하세요.

## 도구 호출 규칙
- 사용자의 요청이 제공된 도구 중 하나에 해당하면, 반드시 해당 도구를 호출하세요. 직접 텍스트로 답변하지 마세요.
- 도구를 호출하지 않는 경우는 오직: 일반 대화, 인사, 지원하지 않는 기능 요청뿐입니다.
- 지원하지 않는 기능 요청: 해당 기능은 없다고 알려주고 비슷한 대체 기능을 제안하세요.
- 예매/예약/티켓 → book. 근처/주변/가까운 영화관 → nearby. 상영시간/뭐해/뭐하 → showtime.

## 매핑 예시
- "근처 영화관 찾아줘" / "가까운 영화관" / "주변 영화관 어디" → nearby 도구
- "이근처 영화관" / "여기 근처" / "이 근처 메가박스" → nearby 도구 (region은 빈 문자열!)
- "신림동 근처 영화관" / "강남 근처 CGV" → nearby 도구 (region에 지역명 채우기)
- "오늘 영화 뉴스" / "다이제스트" / "영화 소식" → digest 도구
- "예매하고 싶어" / "티켓 끊고 싶어" → book 도구
- "강남 영화 뭐해?" / "인터스텔라 상영관" → showtime 도구
- "좌석 보여줘" / "자리 보여줘" / "좌석 배치도" → seat_map 도구
- "부산에서 영화 보려는데" / "내일 4시반 부산역 도착인데 영화 추천" → showtime (지역+시간이 있으면 상영시간 조회!)
- "추천해줘" / "뭐 볼만해" / "볼만한 영화" + 지역/시간 → showtime (추천=상영시간 조회)

## 의도 판별 우선순위
- 지역 + 시간/날짜가 언급되면 → showtime (영화 보려는 맥락)
- "추천"이라는 단어가 있어도 지역/시간이 있으면 → showtime (nearby나 new_movies가 아님!)
- 단순 "추천해줘" (지역/시간 없음) → new_movies 또는 ranking

## reply 작성 규칙
- 도구 호출 시 reply 파라미터에 짧은 안내 메시지를 넣으세요 (실제 데이터는 봇이 따로 붙여줌).
- nearby의 reply에는 위치 전송을 요청하는 안내를 넣으세요.

## nearby 도구 파라미터 규칙
- chain: 메시지에 체인명(CGV, 메가박스, 롯데시네마 등)이 있으면 반드시 채울 것
- region: 구체적 지역명(신림동, 강남, 분당, 이태원 등)이 있으면 반드시 채울 것
- "이근처", "여기", "여기근처", "이 근처" 등 대명사/지시어는 region이 아님 → 빈 문자열

## 대화 맥락
- 이전 대화가 주어질 수 있음. 후속 메시지는 이전 맥락의 보충/수정일 수 있으므로 이전 intent를 참고
- 후속 메시지가 짧고 맥락 없이는 의미를 알기 어려운 경우, 이전 대화의 intent를 유지하고 빠진 정보를 채워넣기
- 중요: 이전 대화에서 언급된 정보(영화 제목, 지역 등)를 params에 반드시 포함하세요"""


# ---------------------------------------------------------------------------
# Provider-specific tool format converters
# ---------------------------------------------------------------------------


def _openai_tools() -> list[dict]:
    """Convert TOOL_DEFINITIONS to OpenAI tools format."""
    tools = []
    for td in TOOL_DEFINITIONS:
        properties = {}
        for name, schema in td["parameters"].items():
            properties[name] = {k: v for k, v in schema.items()}
        tools.append({
            "type": "function",
            "function": {
                "name": td["name"],
                "description": td["description"],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": td.get("required", []),
                },
            },
        })
    return tools


def _anthropic_tools() -> list[dict]:
    """Convert TOOL_DEFINITIONS to Anthropic tools format."""
    tools = []
    for td in TOOL_DEFINITIONS:
        properties = {}
        for name, schema in td["parameters"].items():
            properties[name] = {k: v for k, v in schema.items()}
        tools.append({
            "name": td["name"],
            "description": td["description"],
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": td.get("required", []),
            },
        })
    return tools


def _google_tools():
    """Convert TOOL_DEFINITIONS to Google GenAI tools format."""
    from google.genai import types

    declarations = []
    for td in TOOL_DEFINITIONS:
        properties = {}
        for name, schema in td["parameters"].items():
            kwargs = {"type": schema["type"].upper(), "description": schema.get("description", "")}
            if "enum" in schema:
                kwargs["enum"] = schema["enum"]
            properties[name] = types.Schema(**kwargs)
        declarations.append(types.FunctionDeclaration(
            name=td["name"],
            description=td["description"],
            parameters=types.Schema(
                type="OBJECT",
                properties=properties,
                required=td.get("required", []),
            ),
        ))
    return types.Tool(function_declarations=declarations)


# ---------------------------------------------------------------------------
# LLM classification with function calling
# ---------------------------------------------------------------------------

_DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "google": "gemini-2.0-flash",
}


def classify_intent(
    user_message: str,
    provider_name: str,
    api_key: str,
    model: str = "",
    history: list[dict] | None = None,
) -> ClassificationResult:
    """Classify user intent using native function calling (tool use).

    Uses the same provider/model conventions as digest/llm.py.
    ``history`` is a list of {"role": "user"|"assistant", "content": "..."}
    dicts representing recent conversation turns (for follow-up recognition).
    Raises on API errors — caller should catch and use fallback.
    """
    # Build messages with conversation history for context
    messages = []
    for turn in (history or []):
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})

    if provider_name == "openai":
        import openai

        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model or _DEFAULT_MODELS["openai"],
            messages=[
                {"role": "system", "content": TOOL_SYSTEM_PROMPT},
                *messages,
            ],
            tools=_openai_tools(),
            tool_choice="auto",
            temperature=0.3,
            max_tokens=256,
        )
        return _extract_openai(response)

    elif provider_name == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model or _DEFAULT_MODELS["anthropic"],
            max_tokens=256,
            system=TOOL_SYSTEM_PROMPT,
            messages=messages,
            tools=_anthropic_tools(),
            tool_choice={"type": "auto"},
        )
        return _extract_anthropic(response)

    elif provider_name == "google":
        from google.genai import types

        client = __import__("google.genai", fromlist=["genai"]).Client(api_key=api_key)

        # Build proper multi-turn contents for Google
        contents = []
        for turn in (history or []):
            role = "user" if turn["role"] == "user" else "model"
            contents.append(types.Content(
                role=role,
                parts=[types.Part.from_text(text=turn["content"])],
            ))
        contents.append(types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_message)],
        ))

        config = types.GenerateContentConfig(
            system_instruction=TOOL_SYSTEM_PROMPT,
            tools=[_google_tools()],
            temperature=0.3,
            max_output_tokens=256,
        )
        response = client.models.generate_content(
            model=model or _DEFAULT_MODELS["google"],
            contents=contents,
            config=config,
        )
        return _extract_google(response)

    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")


# ---------------------------------------------------------------------------
# Response extraction (per provider)
# ---------------------------------------------------------------------------


def _extract_openai(response) -> ClassificationResult:
    """Extract ClassificationResult from OpenAI tool call response."""
    message = response.choices[0].message

    if message.tool_calls:
        tc = message.tool_calls[0]
        try:
            intent = Intent(tc.function.name)
        except ValueError:
            return ClassificationResult(intent=Intent.CHAT, reply=message.content or "")
        args = json.loads(tc.function.arguments)
        reply = args.pop("reply", "")
        return ClassificationResult(intent=intent, reply=reply, params=args)

    # No tool call → chat
    return ClassificationResult(intent=Intent.CHAT, reply=message.content or "")


def _extract_anthropic(response) -> ClassificationResult:
    """Extract ClassificationResult from Anthropic tool use response."""
    tool_blocks = [b for b in response.content if b.type == "tool_use"]
    text_blocks = [b for b in response.content if b.type == "text"]

    if tool_blocks:
        tb = tool_blocks[0]
        try:
            intent = Intent(tb.name)
        except ValueError:
            text = text_blocks[0].text if text_blocks else ""
            return ClassificationResult(intent=Intent.CHAT, reply=text)
        args = dict(tb.input)
        reply = args.pop("reply", "")
        return ClassificationResult(intent=intent, reply=reply, params=args)

    # No tool call → chat
    text = text_blocks[0].text if text_blocks else ""
    return ClassificationResult(intent=Intent.CHAT, reply=text)


def _extract_google(response) -> ClassificationResult:
    """Extract ClassificationResult from Google GenAI function call response."""
    parts = response.candidates[0].content.parts

    for part in parts:
        if part.function_call:
            fc = part.function_call
            try:
                intent = Intent(fc.name)
            except ValueError:
                continue
            args = dict(fc.args) if fc.args else {}
            reply = args.pop("reply", "")
            return ClassificationResult(intent=intent, reply=reply, params=args)

    # No function call → chat
    text_parts = [p.text for p in parts if p.text]
    return ClassificationResult(intent=Intent.CHAT, reply="".join(text_parts))


# ---------------------------------------------------------------------------
# Keyword fallback (intent classification only — no param parsing)
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

_SEAT_MAP_KEYWORDS = ["좌석 보여", "좌석 배치", "좌석도", "좌석 현황", "자리 보여", "좌석 사진", "seat map"]
_THEATER_INFO_KEYWORDS = ["상영관", "스크린", "imax", "아이맥스", "4dx", "돌비"]


def _extract_region_for_nearby(text: str, trigger_kw: str, chain: str) -> str:
    """Extract a region/place name from a nearby query.

    Strips the trigger keyword (근처/주변/가까운), chain names, and common
    noise words, then returns whatever meaningful location token remains.
    Examples:
        "신림동 근처 영화관"  → "신림동"
        "강남 근처 CGV"     → "강남"
        "근처 메가박스 찾아줘" → "" (no region)
    """
    import re

    t = text
    # 1) Remove pronoun+trigger compounds FIRST (before splitting trigger kw)
    #    "이근처" / "여기 근처" / "여기근처" → not a real location
    for compound in ("이근처", "여기근처", "이 근처", "여기 근처",
                      "이주변", "여기주변", "이 주변", "여기 주변"):
        t = t.replace(compound, " ")
    # 2) Remove remaining pronouns/demonstratives
    for pronoun in ("여기", "여긴", "이쪽", "우리"):
        t = t.replace(pronoun, " ")
    # 3) Remove trigger keyword
    t = t.replace(trigger_kw, " ")
    # 4) Remove chain names
    for name in ("CGV", "cgv", "씨지브이", "메가박스", "megabox",
                  "롯데시네마", "롯데", "lotte", "씨네q", "cineq"):
        t = re.sub(re.escape(name), " ", t, flags=re.IGNORECASE)
    # 5) Remove common noise words
    for noise in ("영화관", "극장", "시네마", "찾아줘", "찾아", "알려줘",
                   "어디야", "어디", "있어", "있나", "있니", "있지",
                   "뭐", "뭐있지", "뭐있니", "좀", "내일", "오늘",
                   "에서", "보여줘", "보여", "영화", "첫", "뭐해", "뭐하",
                   "야", "요", "the", "a"):
        t = t.replace(noise, " ")
    # Clean up whitespace
    t = re.sub(r"\s+", " ", t).strip()
    # Return the remaining meaningful token(s) if short enough to be a place
    if t and len(t) <= 10:
        return t
    return ""


def classify_intent_fallback(user_message: str) -> ClassificationResult:
    """Keyword-based intent classification when LLM is unavailable.

    This is a degraded mode — only classifies intent with minimal params.
    For full param extraction (showtime region/time, movie titles, etc.),
    an LLM provider must be configured.
    """
    text = user_message.strip()
    msg = text.lower()

    # Preference
    has_preference = any(kw in msg for kw in _PREFERENCE_KEYWORDS)
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

    # Movie info
    for kw in _MOVIE_INFO_KEYWORDS:
        if kw in msg:
            return ClassificationResult(
                intent=Intent.MOVIE_INFO,
                reply="영화 정보를 검색할게요!",
                params={"movie": user_message},
            )

    # Seat map (before showtime — "좌석 보여줘" contains time signals like "시")
    for kw in _SEAT_MAP_KEYWORDS:
        if kw in msg:
            return ClassificationResult(
                intent=Intent.SEAT_MAP,
                reply="좌석 배치도를 가져올게요!",
                params={"region": "", "theater": user_message, "movie": "", "time": "", "date": ""},
            )

    # Showtime
    has_showtime_kw = any(kw in msg for kw in _SHOWTIME_KEYWORDS)
    has_time_signal = any(kw in msg for kw in _SHOWTIME_TIME_SIGNALS)
    if has_showtime_kw or has_time_signal:
        return ClassificationResult(
            intent=Intent.SHOWTIME,
            reply="상영시간을 조회할게요!",
            params={"region": "", "time": "", "date": "", "movie": "", "theater": user_message},
        )

    # Theater info
    for kw in _THEATER_INFO_KEYWORDS:
        if kw in msg:
            return ClassificationResult(
                intent=Intent.THEATER_INFO,
                reply="극장 정보를 조회할게요!",
                params={"query": user_message},
            )

    # Theater list
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

    for ck, cv in _CHAIN_KEYWORDS.items():
        if ck in msg and ("극장" in msg or "영화관" in msg or "목록" in msg):
            return ClassificationResult(
                intent=Intent.THEATER_LIST,
                reply=f"{cv} 극장 목록을 조회할게요!",
                params={"chain": cv, "region": ""},
            )

    # Booking history
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
                reply="예매 링크를 준비할게요! :ticket:",
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
            # Try to extract chain name from message
            chain = ""
            for c in ("CGV", "cgv", "씨지브이"):
                if c in msg:
                    chain = "CGV"
                    break
            for c in ("메가박스", "megabox"):
                if c in msg.lower():
                    chain = "메가박스"
                    break
            for c in ("롯데시네마", "롯데", "lotte"):
                if c in msg.lower():
                    chain = "롯데시네마"
                    break
            # Try to extract region — strip noise words and chain names
            region = _extract_region_for_nearby(text, kw, chain)
            reply = "근처 영화관을 찾아드릴게요! 위치를 전송해주세요."
            if region:
                reply = f"{region} 근처 영화관을 찾아볼게요!"
            return ClassificationResult(
                intent=Intent.NEARBY,
                reply=reply,
                params={"chain": chain, "region": region},
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
            "죄송해요, LLM API 키가 설정되지 않아 자연어 이해가 제한됩니다.\n"
            "환경변수 OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY 중 "
            "하나 이상 설정하거나, 대시보드에서 설정해주세요.\n\n"
            "키워드로도 사용할 수 있어요:\n"
            "• 박스오피스 순위\n"
            "• 근처 영화관\n"
            "• 예매\n"
            "• 예매 내역"
        ),
    )
