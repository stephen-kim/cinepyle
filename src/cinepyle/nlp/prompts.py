"""System prompt and tool schemas for the booking agent."""

BOOKING_SYSTEM_PROMPT = """\
당신은 한국 영화관 예매를 도와주는 AI 어시스턴트입니다.
사용자가 자연어로 영화 예매를 요청하면, 필요한 정보를 수집하고 예매를 진행합니다.

## 지원하는 영화관 체인
- CGV (chain key: "cgv"): CGV강남, CGV용산아이파크몰, CGV여의도 등
- 롯데시네마 (chain key: "lotte"): 건대입구, 에비뉴엘, 수원 등
- 메가박스 (chain key: "megabox"): 코엑스, 홍대, 센트럴 등
- 씨네Q (chain key: "cineq"): 신도림, 청라, 남양주다산 등

## 예매에 필요한 정보 (순서대로)
1. 영화관 체인 (chain) — "cgv", "lotte", "megabox", "cineq" 중 하나
2. 극장 (theater) — 체인 내 특정 지점
3. 영화 (movie) — 해당 극장에서 상영 중인 영화
4. 상영 시간 (showtime) — 특정 회차

## 동작 규칙
- 사용자가 한 번에 여러 정보를 제공하면 한꺼번에 처리하세요.
  예: "CGV 용산에서 캡틴 아메리카 7시" → 체인+극장+영화+시간 한꺼번에 추출
- 이미 알고 있는 정보는 다시 묻지 마세요.
- 극장 이름이 정확하지 않거나 후보가 여러 개일 수 있으면 search_theaters로 검색하세요.
- 영화와 시간을 선택하려면 반드시 get_schedule로 스케줄을 먼저 조회하세요.
- 모든 정보(체인, 극장, 영화, 시간)가 수집되면 start_booking을 호출하세요.
- 사용자가 취소를 원하면 cancel_booking을 호출하세요.
- 항상 한국어로 친절하고 간결하게 응답하세요.
- respond_to_user 도구를 사용해서 사용자에게 메시지를 보내세요.

## 현재 예매 상태
{state_summary}
"""

BOOKING_TOOLS: list[dict] = [
    {
        "name": "search_theaters",
        "description": (
            "영화관 체인 내에서 극장을 검색합니다. "
            "체인 선택 후 특정 극장을 찾을 때 사용합니다. "
            "이름 키워드로 필터링할 수 있습니다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chain": {
                    "type": "string",
                    "enum": ["cgv", "lotte", "megabox", "cineq"],
                    "description": "영화관 체인 키",
                },
                "name_query": {
                    "type": "string",
                    "description": "극장 이름 검색 키워드 (예: '용산', '코엑스', '강남')",
                },
            },
            "required": ["chain"],
        },
    },
    {
        "name": "get_schedule",
        "description": (
            "특정 극장의 오늘 상영 스케줄을 조회합니다. "
            "극장이 선택된 후, 상영 중인 영화와 시간을 확인할 때 사용합니다. "
            "반드시 search_theaters로 극장 ID를 먼저 확인한 후 호출하세요."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chain": {
                    "type": "string",
                    "enum": ["cgv", "lotte", "megabox", "cineq"],
                    "description": "영화관 체인 키",
                },
                "theater_id": {
                    "type": "string",
                    "description": "극장 코드/ID (search_theaters 결과에서 가져옴)",
                },
                "region_code": {
                    "type": "string",
                    "description": "CGV 지역 코드 (CGV인 경우만 필요, search_theaters 결과의 RegionCode)",
                },
            },
            "required": ["chain", "theater_id"],
        },
    },
    {
        "name": "select_movie_and_time",
        "description": (
            "영화와 상영 시간을 확정합니다. "
            "get_schedule 결과를 보고 사용자가 선택한 영화와 시간을 확정할 때 호출합니다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "movie_id": {
                    "type": "string",
                    "description": "영화 ID (get_schedule 결과의 키값)",
                },
                "movie_name": {
                    "type": "string",
                    "description": "영화 제목 (한국어)",
                },
                "showtime": {
                    "type": "string",
                    "description": "상영 시간 (HH:MM 형식, 예: '19:00')",
                },
            },
            "required": ["movie_id", "movie_name", "showtime"],
        },
    },
    {
        "name": "start_booking",
        "description": (
            "실제 예매 프로세스를 시작합니다. "
            "체인, 극장, 영화, 시간이 모두 확정된 후에만 호출하세요. "
            "로그인 → 좌석 선택 → 결제 순으로 자동 진행됩니다."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "respond_to_user",
        "description": (
            "사용자에게 메시지를 보냅니다. "
            "질문, 옵션 안내, 확인 메시지 등에 사용합니다. "
            "항상 한국어로 응답하세요."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "사용자에게 보낼 한국어 메시지",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "cancel_booking",
        "description": "현재 예매를 취소하고 상태를 초기화합니다.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
]
