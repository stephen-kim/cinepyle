# Cinepyle

한국 영화 텔레그램 알림봇 - 박스오피스 순위, 신작 알림, IMAX 상영 알림, 근처 영화관 찾기, AI 영화 뉴스 다이제스트

## 기능

- `/ranking` - 일일 박스오피스 순위 (영화진흥위원회 KOFIC)
- `/nearby` - 근처 영화관 찾기 (CGV, 롯데시네마, 메가박스, 씨네Q, 독립영화관)
- 신작 영화 자동 알림 (박스오피스 + KOFIC 영화목록 API, Watcha Pedia 예상 별점 포함)
- CGV 용산아이파크몰 IMAX 상영 개시 자동 알림
- 📰 AI 데일리 다이제스트 - Daum 영화뉴스, Cine21, Watcha 매거진에서 읽을만한 기사를 AI가 선별·요약하여 매일 전송

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
| `DASHBOARD_PORT` | 대시보드 포트 (기본 `8080`, 선택) |

### 로컬 실행

```bash
uv sync
uv run cinepyle
# 대시보드: http://localhost:8080
```

### Docker

```bash
docker compose up --build
# 대시보드: http://localhost:8080
```

## 대시보드

웹 대시보드 (`localhost:8080`)에서 다이제스트 설정을 관리할 수 있습니다:

- 뉴스 소스 선택 (Daum / Cine21 / Watcha)
- 전송 스케줄 (시간, 활성화)
- LLM 설정 (OpenAI / Anthropic / Google + API Key)
- AI 선별 기준 (자유 텍스트로 취향 입력)
- 테스트 다이제스트 즉시 전송

## 기술 스택

- Python 3.14
- python-telegram-bot (async)
- requests / BeautifulSoup4 (스크래핑)
- FastAPI / Jinja2 (대시보드)
- OpenAI / Anthropic / Google Gemini (AI 큐레이션)
- python-dotenv (환경변수)
- Docker / GitHub Actions (CI/CD)
