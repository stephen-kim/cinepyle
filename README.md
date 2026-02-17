# Cinepyle

한국 영화 텔레그램 알림봇 - 박스오피스 순위, 신작 알림, IMAX 상영 알림, 근처 영화관 찾기, 자연어 예매

## 기능

- `/ranking` - 일일 박스오피스 순위 (영화진흥위원회 KOFIC)
- `/nearby` - 근처 영화관 찾기 (CGV, 롯데시네마, 메가박스, 씨네Q, 독립영화관)
- `/book` - 자연어 영화 예매 (LLM 기반, CGV/롯데시네마/메가박스/씨네Q)
- 매일 아침 9시 영화 다이제스트 (개봉 예정 + 박스오피스 + Watcha 기대평 + 씨네21/네이버 링크)
- 신작 영화 자동 알림 (박스오피스 + KOFIC 영화목록 API, Watcha Pedia 예상 별점 포함)
- CGV 용산아이파크몰 IMAX 상영 개시 자동 알림
- 웹 대시보드 (`localhost:3847`) — 봇 설정을 런타임에 변경 가능
  - 알림 주기 조정 (IMAX / 신작 체크 간격)
  - 선호 영화관 선택
  - LLM 우선순위 드래그 정렬
  - 크리덴셜 / API 키 관리 (암호화 저장)

## 설치 및 실행

### 요구사항

- Python >= 3.14
- [uv](https://docs.astral.sh/uv/)

### 설정

```bash
cp .env.example .env
# .env 파일에 API 키 입력
```

| 환경변수 | 설명 |
|---------|------|
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 알림 받을 텔레그램 채팅방 ID |
| `KOBIS_API_KEY` | [영화진흥위원회 API 키](https://www.kobis.or.kr/kobisopenapi/homepg/main/main.do) |
| `WATCHA_EMAIL` | Watcha Pedia 계정 이메일 |
| `WATCHA_PASSWORD` | Watcha Pedia 계정 비밀번호 |
| `CGV_ID` | CGV 계정 ID (예매용, 선택) |
| `CGV_PASSWORD` | CGV 계정 비밀번호 (예매용, 선택) |
| `LOTTECINEMA_ID` | 롯데시네마 계정 ID (예매용, 선택) |
| `LOTTECINEMA_PASSWORD` | 롯데시네마 계정 비밀번호 (예매용, 선택) |
| `MEGABOX_ID` | 메가박스 계정 ID (예매용, 선택) |
| `MEGABOX_PASSWORD` | 메가박스 계정 비밀번호 (예매용, 선택) |
| `CINEQ_ID` | 씨네Q 계정 ID (예매용, 선택) |
| `CINEQ_PASSWORD` | 씨네Q 계정 비밀번호 (예매용, 선택) |
| `NAVER_MAPS_CLIENT_ID` | 네이버 지도 API Client ID (길찾기용, 선택) |
| `NAVER_MAPS_CLIENT_SECRET` | 네이버 지도 API Client Secret (길찾기용, 선택) |
| `DASHBOARD_PORT` | 웹 대시보드 포트 (기본 `3847`, 선택) |
| `SETTINGS_ENCRYPTION_KEY` | 크리덴셜 암호화 키 (미설정 시 자동 생성, 선택) |

### 로컬 실행

```bash
uv sync
uv run playwright install chromium
uv run cinepyle
# 대시보드: http://localhost:3847
```

### Docker

```bash
docker compose up --build
# 대시보드: http://localhost:3847
```

## 기술 스택

- Python 3.14
- python-telegram-bot (async)
- Playwright (헤드리스 브라우저 스크래핑 - CGV, Watcha 등 CSR 사이트)
- requests / BeautifulSoup4 (API 호출)
- FastAPI + HTMX + Tailwind CSS (웹 대시보드, 빌드 불필요)
- python-dotenv (환경변수)
- Docker / GitHub Actions (CI/CD)
