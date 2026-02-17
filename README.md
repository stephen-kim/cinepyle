# cinePyle

한국 영화 텔레그램 봇 — 박스오피스, 근처 영화관, 자연어 예매, IMAX/신작 알림

## 기능

### 명령어
- `/ranking` — 일일 박스오피스 순위 (영화진흥위원회 KOFIC)
- `/nearby` — 근처 영화관 찾기 (CGV, 롯데시네마, 메가박스, 씨네Q, 독립영화관)
- `/book` — 영화 예매

### 자연어 예매
명령어 없이 자유롭게 말해도 됩니다:
```
"CGV 용산에서 캡틴 아메리카 7시 예매해줘"
"메가박스 코엑스에서 영화 보고 싶어"
"오늘 저녁 롯데시네마 볼만한 거 있어?"
```
LLM이 의도를 파악하고, 체인/극장/영화/시간을 수집한 후 Playwright로 자동 예매합니다.
지원 체인: **CGV** (CAPTCHA 처리 포함), **롯데시네마**, **메가박스**, **씨네Q**

### 자동 알림
- 신작 영화 박스오피스 진입 알림 (Watcha Pedia 예상 별점 포함)
- CGV 용산아이파크몰 IMAX 상영 개시 알림

### AI 자가 치유 스크래퍼
CGV 등 CSR 사이트의 구조가 변경되면 LLM이 자동으로 새로운 추출 전략을 생성합니다.
3단계 폴백: 캐시된 전략 → 하드코딩 JS → LLM 생성

## 설치 및 실행

### 요구사항
- Python >= 3.14
- [uv](https://docs.astral.sh/uv/)

### 설정

```bash
cp .env.example .env
# .env 파일에 API 키 입력
```

| 환경변수 | 설명 | 필수 |
|---------|------|:----:|
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 | O |
| `TELEGRAM_CHAT_ID` | 알림 받을 채팅방 ID | O |
| `KOFIC_API_KEY` | [영화진흥위원회 API 키](https://www.kobis.or.kr/kobisopenapi/homepg/main/main.do) | O |
| `WATCHA_EMAIL` | Watcha Pedia 계정 이메일 | O |
| `WATCHA_PASSWORD` | Watcha Pedia 계정 비밀번호 | O |
| `ANTHROPIC_API_KEY` | Anthropic Claude API 키 | * |
| `OPENAI_API_KEY` | OpenAI API 키 | * |
| `GEMINI_API_KEY` | Google Gemini API 키 | * |
| `CGV_ID` / `CGV_PASSWORD` | CGV 로그인 | |
| `LOTTECINEMA_ID` / `LOTTECINEMA_PASSWORD` | 롯데시네마 로그인 | |
| `MEGABOX_ID` / `MEGABOX_PASSWORD` | 메가박스 로그인 | |

\* LLM API 키는 3개 중 하나만 있으면 됩니다 (우선순위: Anthropic > OpenAI > Gemini)

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

## 아키텍처

```
src/cinepyle/
├── main.py                 # 봇 엔트리포인트
├── config.py               # .env 기반 설정
├── bot/
│   ├── handlers.py         # /ranking, /nearby, /help 핸들러
│   └── booking.py          # LLM 자연어 예매 핸들러
├── nlp/
│   ├── agent.py            # BookingAgent — LLM 오케스트레이션
│   ├── state.py            # 예매 상태 관리
│   ├── prompts.py          # 시스템 프롬프트 + 도구 스키마
│   └── tools.py            # 도구 실행 (극장 검색, 스케줄 조회)
├── booking/
│   ├── base.py             # BookingSession ABC
│   ├── cgv.py              # CGV 예매 (CAPTCHA 처리)
│   ├── lotte.py            # 롯데시네마 예매
│   ├── megabox.py          # 메가박스 예매
│   └── cineq.py            # 씨네Q 예매
├── healing/
│   ├── llm.py              # 멀티 프로바이더 LLM (chat + tool calling)
│   ├── engine.py           # 자가 치유 엔진 (3단계 폴백)
│   └── store.py            # SQLite 전략 캐시
├── scrapers/
│   ├── browser.py          # Playwright 브라우저 관리
│   ├── cgv.py              # CGV 스크래퍼 (Playwright + 자가 치유)
│   ├── watcha.py           # Watcha Pedia 스크래퍼
│   └── boxoffice.py        # KOFIC 박스오피스 API
├── theaters/
│   ├── finder.py           # 근처 영화관 통합 검색
│   ├── cgv.py / lotte.py / megabox.py / cineq.py
│   └── data_*.py           # 극장 정적 데이터
└── notifications/
    ├── imax.py             # IMAX 상영 알림
    └── new_movie.py        # 신작 알림
```

## 기술 스택

- **Python 3.14** + [uv](https://docs.astral.sh/uv/)
- **python-telegram-bot** — async Telegram Bot API
- **Playwright** — 헤드리스 브라우저 (CGV CSR, Watcha 로그인, 예매 자동화)
- **Anthropic / OpenAI / Gemini** — LLM tool calling (자연어 예매 + 자가 치유)
- **requests / BeautifulSoup4** — API 호출 및 HTML 파싱
- **aiosqlite** — 추출 전략 캐시
- **Docker / GitHub Actions** — CI/CD, ghcr.io 자동 배포
