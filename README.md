# Cinepyle

한국 영화 텔레그램 알림봇 - 박스오피스 순위, 신작 알림, IMAX 상영 알림, 근처 영화관 찾기

## 기능

- `/ranking` - 일일 박스오피스 순위 (영화진흥위원회 KOFIC)
- `/nearby` - 근처 영화관 찾기 (CGV, 롯데시네마, 메가박스, 씨네Q, 독립영화관)
- 신작 영화 자동 알림 (박스오피스 + KOFIC 영화목록 API, Watcha Pedia 예상 별점 포함)
- CGV 용산아이파크몰 IMAX 상영 개시 자동 알림

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

### 로컬 실행

```bash
uv sync
uv run playwright install chromium
uv run cinepyle
```

### Docker

```bash
docker compose up --build
```

## 기술 스택

- Python 3.14
- python-telegram-bot (async)
- Playwright (헤드리스 브라우저 스크래핑 - CGV, Watcha 등 CSR 사이트)
- requests / BeautifulSoup4 (API 호출)
- python-dotenv (환경변수)
- Docker / GitHub Actions (CI/CD)
