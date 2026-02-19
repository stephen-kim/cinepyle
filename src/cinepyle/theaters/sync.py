"""Theater & screen sync — fetch from CGV, Lotte, MegaBox APIs.

Fetches theater lists with individual hall/screen names, addresses,
and coordinates.  Each chain can fail independently — partial data
is preserved via TheaterDatabase.update_chain().
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import requests

from datetime import timedelta as _timedelta

from cinepyle.theaters.data_cgv import data as cgv_static_data
from cinepyle.theaters.data_indie import data as indie_static_data
from cinepyle.theaters.models import (
    CGV_GRAD_CD_MAP,
    CGV_GRADE_NAME_MAP,
    LOTTE_SCREEN_TYPE_MAP,
    MEGABOX_SCREEN_TYPE_MAP,
    SCREEN_TYPE_NORMAL,
    SPECIAL_TYPES,
    Screen,
    Theater,
    TheaterDatabase,
)

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Number of days to scan forward for screen discovery.
# Schedule-based APIs only return screens with active showtimes on a given day.
# Scanning multiple days captures screens that are idle today but active later.
_SCREEN_SCAN_DAYS = 7


def _scan_dates() -> list[str]:
    """Return date strings (YYYYMMDD) for multi-day screen scan."""
    base = datetime.now()
    return [(base + _timedelta(days=d)).strftime("%Y%m%d") for d in range(_SCREEN_SCAN_DAYS)]


def _scan_dates_dash() -> list[str]:
    """Return date strings (YYYY-MM-DD) for multi-day screen scan."""
    base = datetime.now()
    return [(base + _timedelta(days=d)).strftime("%Y-%m-%d") for d in range(_SCREEN_SCAN_DAYS)]


# =========================================================================
# CGV
# =========================================================================

CGV_API_BASE = "https://api.cgv.co.kr"
CGV_WEB_BASE = "https://www.cgv.co.kr"
CGV_HMAC_SECRET = "ydqXY0ocnFLmJGHr_zNzFcpjwAsXq_8JcBNURAkRscg"

CGV_REGION_CODES = [
    "01",   # 서울
    "02",   # 경기
    "202",  # 인천
    "03",   # 충청/대전
    "04",   # 전라/광주
    "05",   # 경상/부산/대구
    "06",   # 강원
    "07",   # 제주
]

CGV_REGION_NAME: dict[str, str] = {
    "01": "서울",
    "02": "경기",
    "202": "인천",
    "03": "충청",
    "04": "전라",
    "05": "경상",
    "06": "강원",
    "07": "제주",
}


def _region_from_address(address: str) -> str:
    """Extract broad region name from a Korean address string."""
    addr = address.strip()
    if not addr:
        return ""
    # Match metropolitan cities and provinces
    _ADDR_REGION_MAP = [
        ("서울", "서울"),
        ("인천", "인천"),
        ("대전", "충청"),
        ("세종", "충청"),
        ("대구", "경상"),
        ("부산", "경상"),
        ("울산", "경상"),
        ("광주", "전라"),
        ("경기", "경기"),
        ("강원", "강원"),
        ("충청북도", "충청"), ("충북", "충청"),
        ("충청남도", "충청"), ("충남", "충청"),
        ("전라북도", "전라"), ("전북", "전라"),
        ("전라남도", "전라"), ("전남", "전라"),
        ("경상북도", "경상"), ("경북", "경상"),
        ("경상남도", "경상"), ("경남", "경상"),
        ("제주", "제주"),
    ]
    for prefix, region in _ADDR_REGION_MAP:
        if addr.startswith(prefix) or prefix in addr[:10]:
            return region
    return ""


_cgv_session: requests.Session | None = None


def _cgv_ensure_session() -> requests.Session:
    """Return a shared session with Cloudflare cookies."""
    global _cgv_session
    if _cgv_session is None:
        _cgv_session = requests.Session()
        _cgv_session.headers.update({"User-Agent": _UA})
        _cgv_session.get(CGV_WEB_BASE, timeout=10)  # get CF cookies
    return _cgv_session


def _cgv_get(pathname: str, params: str = "") -> dict | list | None:
    """Make an authenticated GET request to the CGV API.

    ``pathname`` is e.g. "/cnm/site/searchRegnSiteList" (no query string).
    ``params`` is the query string without "?" e.g. "coCd=A420&regnGrpCd=01".
    HMAC signs only the pathname — the query string must NOT be included.
    """
    session = _cgv_ensure_session()
    timestamp = str(int(time.time()))
    message = f"{timestamp}|{pathname}|"
    signature = base64.b64encode(
        hmac.new(
            CGV_HMAC_SECRET.encode(), message.encode(), hashlib.sha256,
        ).digest()
    ).decode()
    url = f"{CGV_API_BASE}{pathname}"
    if params:
        url += f"?{params}"
    headers = {
        "X-TIMESTAMP": timestamp,
        "X-SIGNATURE": signature,
        "Origin": CGV_WEB_BASE,
        "Referer": f"{CGV_WEB_BASE}/",
    }
    resp = session.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        logger.debug("CGV GET %s → %s", pathname, resp.status_code)
        return None
    return resp.json()


def _classify_cgv_screen(grade_name: str, screen_name: str) -> str:
    """Determine screen type from CGV grade/screen names."""
    for keyword, stype in CGV_GRADE_NAME_MAP.items():
        if keyword in grade_name.upper() or keyword in screen_name.upper():
            return stype
    upper = screen_name.upper()
    if "4DX" in upper:
        return "4dx"
    if "SCREENX" in upper:
        return "screenx"
    if "IMAX" in upper:
        return "imax"
    if "DOLBY" in upper:
        return "dolby_atmos"
    if "PREMIUM" in upper or "CINE DE CHEF" in upper.replace(" ", " "):
        return "premium"
    return SCREEN_TYPE_NORMAL


def sync_cgv() -> list[Theater]:
    """Fetch CGV theaters with individual hall names from schedule API."""
    # Build lat/lon lookup from static data (API doesn't return coordinates)
    static_lookup: dict[str, dict] = {
        t["TheaterCode"]: t for t in cgv_static_data
    }

    # Step 1: Get all theaters per region (includes address + special screen types)
    theater_info: dict[str, dict] = {}  # siteNo → info
    for region_code in CGV_REGION_CODES:
        try:
            data = _cgv_get(
                "/cnm/site/searchRegnSiteList",
                f"coCd=A420&regnGrpCd={region_code}",
            )
            if not data:
                continue
            # API wraps in {"statusCode": 0, "data": [...]}
            site_list = data.get("data", data.get("list", data.get("siteList", [])))
            if not isinstance(site_list, list):
                site_list = []
            for site in site_list:
                site_no = str(site.get("siteNo", ""))
                if not site_no:
                    continue
                theater_info[site_no] = {
                    "name": site.get("siteNm", ""),
                    "address": (
                        f"{site.get('rpbldRnmadr', '')} "
                        f"{site.get('rpbldRdnmDaddr', '')}"
                    ).strip(),
                    "grad_list": site.get("rcmGradList", []),
                    "region": CGV_REGION_NAME.get(region_code, ""),
                }
        except Exception:
            logger.exception("CGV region %s sync failed", region_code)

    # Step 2: For each theater, get individual halls from schedule API
    # Scan multiple days to discover screens that are idle today
    scan_dates = _scan_dates()
    theaters: list[Theater] = []

    for site_no, info in theater_info.items():
        static = static_lookup.get(site_no, {})
        lat = float(static.get("Latitude", 0))
        lon = float(static.get("Longitude", 0))

        seen_screens: set[str] = set()
        screens: list[Screen] = []

        # Try to get individual halls from schedule (multi-day scan)
        for scan_date in scan_dates:
            try:
                sched_data = _cgv_get(
                    "/cnm/atkt/searchMovScnInfo",
                    f"coCd=A420&siteNo={site_no}&scnYmd={scan_date}&rtctlScopCd=01",
                )
                if not sched_data:
                    continue
                # API wraps in {"statusCode": 0, "data": [...]}
                raw = sched_data.get("data", sched_data)
                items = (
                    raw
                    if isinstance(raw, list)
                    else raw.get("list", raw.get("movieScnList", []))
                )

                for item in items:
                    scns_no = str(item.get("scnsNo", ""))
                    scns_nm = item.get("expoScnsNm", "") or item.get("scnsNm", "")
                    grade_nm = item.get("tcscnsGradNm", "")
                    seat_count = int(item.get("stcnt", 0) or 0)

                    screen_key = f"{scns_no}_{scns_nm}"
                    if screen_key in seen_screens:
                        continue
                    seen_screens.add(screen_key)

                    screen_type = _classify_cgv_screen(grade_nm, scns_nm)
                    screens.append(Screen(
                        screen_id=scns_no,
                        name=scns_nm,
                        screen_type=screen_type,
                        seat_count=seat_count,
                        is_special=screen_type in SPECIAL_TYPES,
                    ))
            except Exception:
                logger.debug("CGV schedule fetch failed for %s on %s", site_no, scan_date)

        # Fallback: if schedule returned no screens, use rcmGradList
        if not screens:
            for grad in info.get("grad_list", []):
                grad_cd = str(grad.get("gradCd", ""))
                grad_nm = grad.get("gradNm", "")
                grad_count = int(grad.get("gradCount", 1))
                screen_type = CGV_GRAD_CD_MAP.get(grad_cd, SCREEN_TYPE_NORMAL)
                name = grad_nm
                if grad_count > 1:
                    name = f"{grad_nm} ({grad_count}개)"
                screens.append(Screen(
                    screen_id=f"type_{grad_cd}",
                    name=name,
                    screen_type=screen_type,
                    seat_count=0,
                    is_special=screen_type in SPECIAL_TYPES,
                ))

        site_nm = info["name"]
        display_name = site_nm if site_nm.startswith("CGV") else f"CGV{site_nm}"
        theaters.append(Theater(
            chain="cgv",
            theater_code=site_no,
            name=display_name,
            region=info.get("region", ""),
            address=info.get("address", ""),
            latitude=lat,
            longitude=lon,
            screens=screens,
        ))

    logger.info("CGV sync: %d theaters", len(theaters))
    return theaters


# =========================================================================
# Lotte Cinema
# =========================================================================

LOTTE_CINEMA_URL = "http://www.lottecinema.co.kr/LCWS/Cinema/CinemaData.aspx"
LOTTE_TICKETING_URL = "http://www.lottecinema.co.kr/LCWS/Ticketing/TicketingData.aspx"


def _lotte_payload(**kwargs: str) -> bytes:
    param_list = {"channelType": "MW", "osType": "", "osVersion": "", **kwargs}
    data = {"ParamList": json.dumps(param_list)}
    return urlencode(data).encode("utf8")


def _lotte_api(url: str, **kwargs: str) -> dict:
    payload = _lotte_payload(**kwargs)
    with urlopen(url, data=payload, timeout=15) as fin:
        return json.loads(fin.read().decode("utf8"))


def sync_lotte() -> list[Theater]:
    """Fetch Lotte Cinema theaters with individual halls."""
    # Step 1: Get all cinemas
    data = _lotte_api(LOTTE_CINEMA_URL, MethodName="GetCinemaItems")
    items = data.get("Cinemas", {}).get("Items", [])
    items = [x for x in items if x.get("DivisionCode") != 2]

    theaters: list[Theater] = []
    scan_dates = _scan_dates_dash()

    for cinema in items:
        cinema_id = str(cinema.get("CinemaID", ""))
        division_code = str(cinema.get("DivisionCode", ""))
        detail_div_code = str(cinema.get("DetailDivisionCode", ""))
        sort_seq = str(cinema.get("SortSequence", ""))
        name = cinema.get("CinemaNameKR", "")
        lat = float(cinema.get("Latitude", 0) or 0)
        lon = float(cinema.get("Longitude", 0) or 0)

        # Step 2: Get full address
        address = ""
        try:
            detail = _lotte_api(
                LOTTE_CINEMA_URL,
                MethodName="GetCinemaDetailItem",
                divisionCode=division_code,
                detailDivisionCode=detail_div_code,
                cinemaID=cinema_id,
                memberOnNo="",
            )
            address = (
                detail.get("CinemaDetail", {}).get("Item", {}).get("Address", "")
            )
        except Exception:
            logger.debug("Lotte detail failed for %s", cinema_id)

        # Step 3: Get screens from multi-day schedule scan
        seen_screens: set[str] = set()
        screens: list[Screen] = []
        composite_id = f"{division_code}|{sort_seq}|{cinema_id}"

        for scan_date in scan_dates:
            try:
                sched = _lotte_api(
                    LOTTE_TICKETING_URL,
                    MethodName="GetPlaySequence",
                    playDate=scan_date,
                    cinemaID=composite_id,
                    representationMovieCode="",
                )

                for entry in sched.get("PlaySeqs", {}).get("Items", []):
                    screen_id_val = str(entry.get("ScreenID", ""))
                    screen_name = entry.get("ScreenNameKR", "")
                    screen_div = str(entry.get("ScreenDivisionCode", "100"))
                    seat_count = int(entry.get("TotalSeatCount", 0) or 0)

                    screen_key = f"{screen_div}_{screen_name}"
                    if screen_key in seen_screens:
                        continue
                    seen_screens.add(screen_key)

                    screen_type = LOTTE_SCREEN_TYPE_MAP.get(
                        screen_div, SCREEN_TYPE_NORMAL,
                    )
                    screens.append(Screen(
                        screen_id=screen_key,
                        name=screen_name,
                        screen_type=screen_type,
                        seat_count=seat_count,
                        is_special=screen_type in SPECIAL_TYPES,
                    ))
            except Exception:
                logger.debug("Lotte schedule failed for %s on %s", cinema_id, scan_date)

        theaters.append(Theater(
            chain="lotte",
            theater_code=cinema_id,
            name=f"{name} 롯데시네마",
            region=_region_from_address(address),
            address=address,
            latitude=lat,
            longitude=lon,
            screens=screens,
        ))

    logger.info("Lotte sync: %d theaters", len(theaters))
    return theaters


# =========================================================================
# MegaBox
# =========================================================================

MEGABOX_URL = "https://www.megabox.co.kr/on/oh/ohc/Brch/schedulePage.do"
MEGABOX_THEATER_LIST_URL = "https://www.megabox.co.kr/theater/list"


def _megabox_all_branches(session: requests.Session) -> dict[str, str]:
    """Scrape the full theater list (brchNo → name) from the HTML page."""
    import re
    from html import unescape

    resp = session.get(MEGABOX_THEATER_LIST_URL, timeout=15)
    resp.raise_for_status()
    pairs = re.findall(r"brchNo=(\d{4})[^>]*>([^<]+)<", resp.text)
    return {code: unescape(name.strip()) for code, name in pairs}


def sync_megabox() -> list[Theater]:
    """Fetch all MegaBox theaters with individual halls.

    Step 1: Scrape the full theater list from the HTML page (117+ theaters).
    Step 2: For each branch, fetch schedule across multiple days to discover
            all halls (some halls may be idle on any given day).
    """
    from html import unescape as _unescape

    scan_dates = _scan_dates()
    session = requests.Session()
    session.headers.update({
        "User-Agent": _UA,
        "Referer": "https://www.megabox.co.kr/",
    })

    # Step 1: Get full theater list from HTML
    try:
        all_branches = _megabox_all_branches(session)
    except Exception:
        logger.exception("MegaBox theater list page failed")
        return []

    theaters: list[Theater] = []

    # Step 2: Fetch per-branch schedule + details (multi-day scan)
    for brch_no, brch_name in all_branches.items():
        address, lat, lon = "", 0.0, 0.0
        seen: set[str] = set()
        screens: list[Screen] = []

        for scan_date in scan_dates:
            try:
                resp = session.post(
                    MEGABOX_URL,
                    data={
                        "masterType": "brch",
                        "brchNo": brch_no,
                        "brchNo1": brch_no,
                        "playDe": scan_date,
                        "firstAt": "Y",
                    },
                    timeout=10,
                )
                mega = resp.json().get("megaMap", {})

                # Branch info (only grab once)
                if not address:
                    info = mega.get("brchInfo", {})
                    address = _unescape(info.get("roadNmAddr", "") or "")
                    lat = float(info.get("brchLat", 0) or 0)
                    lon = float(info.get("brchLon", 0) or 0)

                # Individual halls from schedule
                for item in mega.get("movieFormList", []):
                    theab_no = str(item.get("theabNo", ""))
                    if theab_no in seen:
                        continue
                    seen.add(theab_no)

                    kind_cd = item.get("theabKindCd", "NOR")
                    screen_type = MEGABOX_SCREEN_TYPE_MAP.get(
                        kind_cd, SCREEN_TYPE_NORMAL,
                    )
                    screens.append(Screen(
                        screen_id=theab_no,
                        name=_unescape(item.get("theabExpoNm", "")),
                        screen_type=screen_type,
                        seat_count=int(item.get("totSeatCnt", 0) or 0),
                        is_special=screen_type in SPECIAL_TYPES,
                    ))
            except Exception:
                logger.debug("MegaBox fetch failed for %s on %s", brch_no, scan_date)

        theaters.append(Theater(
            chain="megabox",
            theater_code=brch_no,
            name=f"{brch_name} 메가박스",
            region=_region_from_address(address),
            address=address,
            latitude=lat,
            longitude=lon,
            screens=screens,
        ))

    logger.info("MegaBox sync: %d theaters", len(theaters))
    return theaters


# =========================================================================
# Indie & CineQ (static data)
# =========================================================================


def _indie_region(raw_region: str) -> str:
    """Extract broad region from indie data Region field like '서울 강남구'."""
    if not raw_region:
        return ""
    first = raw_region.split()[0] if raw_region else ""
    # Map to canonical region names
    _MAP = {
        "서울": "서울", "인천": "인천", "경기": "경기", "강원": "강원",
        "충북": "충청", "충남": "충청", "대전": "충청", "세종": "충청",
        "전북": "전라", "전남": "전라", "광주": "전라",
        "경북": "경상", "경남": "경상", "대구": "경상", "부산": "경상", "울산": "경상",
        "제주": "제주",
    }
    return _MAP.get(first, _region_from_address(raw_region))


def sync_indie_cineq() -> list[Theater]:
    """Convert static indie/CineQ data to Theater objects."""
    theaters: list[Theater] = []
    for t in indie_static_data:
        chain = "cineq" if t.get("Type") == "cineq" else "indie"
        raw_region = t.get("Region", "")
        theaters.append(Theater(
            chain=chain,
            theater_code=t.get("TheaterCode", t["TheaterName"]),
            name=t["TheaterName"],
            region=_indie_region(raw_region),
            address=t.get("Address", raw_region),
            latitude=float(t.get("Latitude", 0)),
            longitude=float(t.get("Longitude", 0)),
            screens=[],  # no screen info available
        ))
    logger.info("Indie/CineQ sync: %d theaters", len(theaters))
    return theaters


# =========================================================================
# Orchestrator
# =========================================================================


def sync_all_theaters() -> TheaterDatabase:
    """Sync all chains and return updated database.

    Each chain fails independently. Existing data for a chain is
    only replaced if the new fetch succeeds (partial update safe).
    """
    db = TheaterDatabase.load()

    chain_syncs: list[tuple[str, callable]] = [
        ("cgv", sync_cgv),
        ("lotte", sync_lotte),
        ("megabox", sync_megabox),
    ]

    for chain, sync_fn in chain_syncs:
        try:
            theaters = sync_fn()
            if theaters:
                db.update_chain(chain, theaters)
                logger.info("Updated %s: %d theaters", chain, len(theaters))
            else:
                logger.warning("%s sync returned empty, keeping old data", chain)
        except Exception:
            logger.exception("Failed to sync %s, keeping old data", chain)

    # Indie/CineQ — always update from static data
    try:
        indie = sync_indie_cineq()
        # Group by chain (cineq vs indie)
        by_chain: dict[str, list[Theater]] = {}
        for t in indie:
            by_chain.setdefault(t.chain, []).append(t)
        for chain, chain_theaters in by_chain.items():
            db.update_chain(chain, chain_theaters)
    except Exception:
        logger.exception("Failed to sync indie/cineq")

    db.last_sync_at = datetime.now(timezone.utc).isoformat()
    db.save()
    return db
