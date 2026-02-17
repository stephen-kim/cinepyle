"""Naver Maps directions URL generation.

Generates deep links and web fallback URLs for directions
from the user's location to a theater.
"""

from __future__ import annotations

from urllib.parse import quote

# App identifier for Naver Maps URL Scheme
_APP_NAME = "cinepyle"


def naver_directions_url(
    start_lat: float,
    start_lng: float,
    dest_lat: float,
    dest_lng: float,
    dest_name: str,
    start_name: str = "내 위치",
) -> dict[str, str]:
    """Generate Naver Maps direction URLs.

    Returns a dict with:
        - "app": nmap:// deep link (opens Naver Map app on mobile)
        - "web": map.naver.com fallback (opens in browser)
        - "mobile_web": m.map.naver.com (mobile browser fallback)
    """
    dest_name_encoded = quote(dest_name)
    start_name_encoded = quote(start_name)

    app_url = (
        f"nmap://route/public?"
        f"slat={start_lat}&slng={start_lng}&sname={start_name_encoded}"
        f"&dlat={dest_lat}&dlng={dest_lng}&dname={dest_name_encoded}"
        f"&appname={_APP_NAME}"
    )

    web_url = (
        f"https://map.naver.com/index.nhn?"
        f"slat={start_lat}&slng={start_lng}&stext={start_name_encoded}"
        f"&elat={dest_lat}&elng={dest_lng}&etext={dest_name_encoded}"
        f"&menu=route&pathType=0"
    )

    mobile_web_url = (
        f"https://m.map.naver.com/route.nhn?"
        f"menu=route"
        f"&sname={start_name_encoded}&sx={start_lng}&sy={start_lat}"
        f"&ename={dest_name_encoded}&ex={dest_lng}&ey={dest_lat}"
        f"&pathType=0&showMap=true"
    )

    return {
        "app": app_url,
        "web": web_url,
        "mobile_web": mobile_web_url,
    }


def format_directions_message(
    start_lat: float,
    start_lng: float,
    dest_lat: float,
    dest_lng: float,
    dest_name: str,
    start_name: str = "내 위치",
) -> str:
    """Format a user-friendly directions message with clickable links."""
    urls = naver_directions_url(
        start_lat, start_lng, dest_lat, dest_lng, dest_name, start_name
    )
    return (
        f"🗺 {dest_name} 길찾기\n"
        f"📱 네이버 지도 앱: {urls['app']}\n"
        f"🌐 웹: {urls['mobile_web']}"
    )
