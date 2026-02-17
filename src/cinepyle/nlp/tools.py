"""Tool execution functions for the booking agent.

Each tool is called by the LLM via structured tool calling.
The executor runs the tool and returns a text result to feed back to the LLM.
"""

from __future__ import annotations

import logging

from cinepyle.nlp.state import BookingState
from cinepyle.theaters import cgv, cineq, lotte, megabox

logger = logging.getLogger(__name__)

_THEATER_MODULES = {
    "cgv": cgv,
    "lotte": lotte,
    "megabox": megabox,
    "cineq": cineq,
}


async def execute_tool(
    tool_name: str,
    arguments: dict,
    state: BookingState,
) -> str:
    """Execute a tool call and return the result as a string for the LLM.

    Special return values:
        "BOOKING_START" — signals the agent to start the deterministic booking flow
        "CANCELLED" — signals the agent to cancel and reset
    """
    try:
        if tool_name == "search_theaters":
            return await _exec_search_theaters(arguments, state)
        elif tool_name == "get_schedule":
            return await _exec_get_schedule(arguments, state)
        elif tool_name == "select_movie_and_time":
            return _exec_select_movie_time(arguments, state)
        elif tool_name == "start_booking":
            return _exec_start_booking(state)
        elif tool_name == "respond_to_user":
            return arguments.get("message", "")
        elif tool_name == "cancel_booking":
            return "CANCELLED"
        else:
            return f"알 수 없는 도구: {tool_name}"
    except Exception:
        logger.exception("Tool execution failed: %s", tool_name)
        return f"도구 실행 실패: {tool_name}"


async def _exec_search_theaters(args: dict, state: BookingState) -> str:
    """Search theaters by chain and optional name keyword."""
    chain = args["chain"]
    name_query = args.get("name_query", "")

    if chain not in _THEATER_MODULES:
        return f"지원하지 않는 체인: {chain}"

    module = _THEATER_MODULES[chain]
    theaters = module.get_theater_list()

    if name_query:
        theaters = [
            t
            for t in theaters
            if name_query in t.get("TheaterName", "")
        ]

    # Limit to 15 results
    theaters = theaters[:15]
    state.chain = chain
    state.available_theaters = theaters

    if not theaters:
        return f"'{name_query}'에 해당하는 극장을 찾을 수 없습니다."

    lines = []
    for t in theaters:
        tid = t.get("TheaterCode", t.get("TheaterID", t.get("brchNo", "")))
        name = t.get("TheaterName", "")
        region = t.get("RegionCode", "")
        line = f"- {name} (ID: {tid})"
        if region:
            line += f" [RegionCode: {region}]"
        lines.append(line)

    return f"검색 결과 ({len(theaters)}개):\n" + "\n".join(lines)


async def _exec_get_schedule(args: dict, state: BookingState) -> str:
    """Fetch today's schedule for a theater."""
    chain = args["chain"]
    theater_id = args["theater_id"]

    state.chain = chain
    state.theater_id = theater_id

    # Resolve theater name from available_theaters
    for t in state.available_theaters:
        tid = str(
            t.get("TheaterCode", t.get("TheaterID", t.get("brchNo", "")))
        )
        if tid == str(theater_id):
            state.theater_name = t.get("TheaterName", "")
            if chain == "cgv":
                state.theater_region = t.get("RegionCode", "")
            break

    try:
        if chain == "cgv":
            # CGV is async and returns formatted text
            region = args.get("region_code") or state.theater_region or ""
            text = await cgv.get_movie_schedule(region, theater_id)
            return f"CGV 상영 스케줄:\n{text}"
        else:
            # Lotte, MegaBox, CineQ are sync and return dict
            module = _THEATER_MODULES[chain]
            schedule = module.get_movie_schedule(theater_id)
            state.available_movies = schedule

            if not schedule:
                return "현재 상영 중인 영화가 없습니다."

            return _format_schedule(schedule)
    except Exception:
        logger.exception("Schedule fetch failed: %s/%s", chain, theater_id)
        return "스케줄 조회에 실패했습니다. 잠시 후 다시 시도해주세요."


def _format_schedule(schedule: dict) -> str:
    """Format a schedule dict into readable text for the LLM."""
    lines = ["상영 스케줄:"]
    for key, info in schedule.items():
        name = info.get("Name", key)
        schedules = info.get("Schedules", [])
        if not schedules:
            lines.append(f"- {name} (ID: {key}): 상영 시간 없음")
            continue

        time_parts = []
        for s in schedules:
            start = s.get("StartTime", "")
            remaining = s.get("RemainingSeat", "?")
            time_parts.append(f"{start}({remaining}석)")

        lines.append(f"- {name} (ID: {key}): {', '.join(time_parts)}")

    return "\n".join(lines)


def _exec_select_movie_time(args: dict, state: BookingState) -> str:
    """Confirm movie and showtime selection."""
    state.movie_id = args["movie_id"]
    state.movie_name = args["movie_name"]
    state.showtime = args["showtime"]

    return (
        f"선택 완료: {state.movie_name} {state.showtime}\n"
        f"예매를 시작하려면 start_booking을 호출하세요."
    )


def _exec_start_booking(state: BookingState) -> str:
    """Validate all fields are present and signal booking start."""
    missing = state.missing_fields()
    if missing:
        return (
            f"아직 필요한 정보가 부족합니다: {', '.join(missing)}\n"
            f"먼저 모든 정보를 수집해주세요."
        )
    return "BOOKING_START"
