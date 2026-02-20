# Cinepyle

한국 영화관 정보를 자연어로 조회하는 텔레그램 봇.

상영시간, 좌석 배치도, 근처 영화관 찾기, 박스오피스, 예매 내역, 영화 뉴스 등을 하나의 챗봇에서 처리합니다.

## 주요 기능

### 자연어 대화

LLM(OpenAI / Anthropic / Google)의 function calling으로 의도를 분류합니다. LLM이 없으면 키워드 기반 폴백으로 동작합니다.

```
"강남에서 저녁 7시에 인터스텔라 하는 데 있어?"  → 상영시간 조회
"근처에 왕과 사는 남자 하는 곳 있어? 이시간에"  → 위치 요청 → 근처 극장 상영 정보
"인터스텔라 재밌어?"                            → 영화 정보 + Watcha 평점
"CGV용산 좌석 보여줘"                           → 좌석 배치도 스크린샷
```

### 상영시간 조회

- 지역 / 극장 / 영화 / 시간 / 날짜 / 특수관 조합 검색
- 전국 검색 (시드 DB 기반, 영화 제목 필수)
- 14일치 상영 데이터 저장
- IMAX, 4DX, 돌비시네마, 스크린X 등 특수관 필터
- 선호 극장 / 상영관 우선 표시

### 근처 영화관

- GPS 위치 전송으로 가까운 극장 검색
- 텍스트 지역명 검색 ("신림동 근처 CGV")
- 영화 + 시간 필터 ("근처에 파묘 지금 하는 곳")
- 체인 필터 (CGV, 롯데시네마, 메가박스)

### 좌석 배치도

- Playwright로 예매 페이지 접속 후 좌석 현황 스크린샷 캡처
- CGV, 롯데시네마, 메가박스, 씨네Q 지원
- 영화 / 시간 / 극장 매칭 후 자동 네비게이션

### 영화 정보

- KOFIC API: 감독, 출연진, 장르, 러닝타임, 등급, 제작국
- Watcha: 평균 평점 + 개인화 예상 평점
- 동명 영화 구분 (연도 / 감독 표시 후 번호 선택)

### 박스오피스

- 일일 박스오피스 순위 (KOFIC API)
- Watcha 평점 병렬 조회
- KOFIC 실패 시 Watcha 박스오피스 폴백

### 예매

- CGV, 롯데시네마, 메가박스 예매 딥링크
- 모바일 앱 연동 (앱 설치 시 앱에서 열림)

### 예매 내역

- CGV / 롯데 / 메가박스 예매 기록 자동 조회
- Playwright 로그인 + CAPTCHA 자동 처리 (LLM 비전)

### 영화 뉴스 다이제스트

- 소스: Google News RSS, Cine21, Watcha Magazine
- LLM 큐레이션 (선호 키워드 기반 필터링)
- 매일 자동 발송 또는 수동 요청

### 알림

| 알림 | 주기 | 설명 |
|------|------|------|
| IMAX 상영 | 30초 | CGV용산 IMAX 신규 상영 감지 |
| 신작 개봉 | 1시간 | 새 영화 등장 시 알림 (장르, Watcha 평점 포함) |
| 스크린 알림 | 설정 가능 | 특정 극장 / 상영관의 새 영화 감지 |
| 일일 다이제스트 | 매일 1회 | 영화 뉴스 요약 (KST 시간 설정 가능) |

### 선호 설정

- 선호 극장 등록 / 해제 ("선호 극장 CGV용산 추가해줘")
- 선호 상영관 타입 설정 ("IMAX 선호 설정해줘")
- 상영시간 조회 시 ⭐ 마크로 우선 표시

## 지원 극장 체인

| 체인 | 상영시간 | 좌석 배치도 | 예매 내역 |
|------|---------|------------|----------|
| CGV | ✅ | ✅ | ✅ |
| 롯데시네마 | ✅ | ✅ | ✅ |
| 메가박스 | ✅ | ✅ | ✅ |
| 씨네Q | ✅ | ✅ | - |
| 독립영화관 | - | - | - |

특수관: IMAX, 4DX, ScreenX, Dolby Atmos, Dolby Cinema, SuperPlex, 샤롯데, 컴포트, 부티크, 리클라이너, 프리미엄

## 설치 및 실행

### 환경변수

```env
# 필수
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
KOFIC_API_KEY=your-kofic-key

# LLM (하나 이상 설정)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AI...

# 선택 — Watcha 평점
WATCHA_EMAIL=your@email.com
WATCHA_PASSWORD=your-password

# 선택 — 예매 내역 / 좌석 배치도 (체인별 로그인)
CGV_ID=your-cgv-id
CGV_PASSWORD=your-cgv-password
LOTTECINEMA_ID=your-lotte-id
LOTTECINEMA_PASSWORD=your-lotte-password
MEGABOX_ID=your-megabox-id
MEGABOX_PASSWORD=your-megabox-password

# 선택 — 대시보드
DASHBOARD_PORT=3847
```

### Docker (권장)

```bash
docker compose up -d
```

Watchtower가 매시간 새 이미지를 자동 감지하여 업데이트합니다.

### 로컬 실행

```bash
uv sync
playwright install chromium
uv run cinepyle
```

## 대시보드

웹 대시보드 (`localhost:3847`)에서 설정을 관리할 수 있습니다:

- 극장 데이터 조회 (지역별, 체인별, 상영관 정보)
- 다이제스트 설정 (뉴스 소스, 전송 시간, LLM 설정, AI 선별 기준)
- 극장 동기화 수동 실행

## 아키텍처

```
Telegram ←→ python-telegram-bot (polling)
              ├── NLP 분류 (LLM function calling / keyword fallback)
              ├── 상영시간 조회 (CGV / 롯데 / 메가박스 API)
              ├── 좌석 캡처 (Playwright)
              ├── 영화 정보 (KOFIC API + Watcha)
              ├── 알림 (IMAX / 신작 / 스크린 / 다이제스트)
              └── 대시보드 (FastAPI, port 3847)

GitHub Actions
  ├── sync-theaters.yml  — 매일 극장 데이터 동기화 → seed/theaters.db 커밋
  └── docker.yml         — Docker 이미지 빌드 → ghcr.io 배포
```

### 데이터 흐름

1. **극장 동기화**: GitHub Actions가 매일 CGV / 롯데 / 메가박스 API에서 극장, 상영관, 14일치 상영 정보를 수집하여 `seed/theaters.db`에 커밋
2. **Docker 배포**: 시드 DB가 포함된 이미지가 ghcr.io에 배포
3. **봇 시작**: 시드 DB를 로드하여 인메모리 캐시로 사용
4. **실시간 조회**: 상영시간 조회 시 각 체인 API에 직접 요청

### CI 안전장치

극장 동기화 시 체인별 상영관 수집률을 검증합니다. 한 체인이라도 90% 미만이면 CI가 실패하여 깨진 데이터가 커밋되지 않습니다.

## 기술 스택

- **Python 3.14** / uv
- **python-telegram-bot** — 텔레그램 봇 프레임워크
- **LLM** — OpenAI, Anthropic, Google GenAI (의도 분류, 영화 매칭, CAPTCHA, 다이제스트 큐레이션)
- **Playwright** — 좌석 배치도, 예매 내역, CAPTCHA
- **SQLAlchemy** — 극장 / 상영 데이터 저장
- **FastAPI + Jinja2** — 웹 대시보드
- **requests + BeautifulSoup** — 스크래핑
- **Docker + Watchtower** — 배포 및 자동 업데이트
- **GitHub Actions** — CI/CD (극장 동기화, Docker 빌드)
