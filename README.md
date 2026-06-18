# Cinepyle

텔레그램으로 영화 뉴스 다이제스트를 자동 전송하는 서비스입니다.

## 기능

- Google News RSS, Cine21, Watcha Magazine에서 영화 관련 글 수집
- OpenAI / Anthropic / Google GenAI 중 설정된 LLM으로 기사 선별 및 요약
- LLM 설정이 없거나 실패하면 수집 기사 기반 폴백 다이제스트 전송
- `config/settings.json`의 스케줄 설정에 따라 매일 1회 KST 기준 전송
- Docker 이미지 빌드 후 GHCR 배포, Watchtower 자동 업데이트

## 환경변수

```env
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id

# LLM: 하나 이상 설정하면 AI 큐레이션 사용
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AI...

# 선택: 명시적 provider/model override
LLM_PROVIDER=openai
LLM_MODEL=
LLM_API_KEY=
```

## 실행

### Docker

```bash
docker compose up -d
```

`docker-compose.yml`에는 Watchtower가 포함되어 있습니다. `master` 브랜치에 push하면 GitHub Actions가 `ghcr.io/stephen-kim/cinepyle:latest` 이미지를 빌드/푸시하고, 서버의 Watchtower가 새 이미지를 감지해 컨테이너를 갱신합니다.

### 로컬

```bash
uv sync
uv run cinepyle
```

## GitHub Actions

- `.github/workflows/docker.yml`: `master` push 또는 PR에서 Docker 이미지 빌드
- 극장/상영관 데이터 동기화 workflow는 사용하지 않습니다.

## 기술 스택

- Python 3.14 / uv
- python-telegram-bot job queue
- requests + BeautifulSoup
- OpenAI / Anthropic / Google GenAI
- Docker + Watchtower
- GitHub Actions
