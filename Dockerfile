FROM python:3.14-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install system dependencies for Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libatspi2.0-0 libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency specification first for layer caching
COPY pyproject.toml ./

# Install dependencies without the project itself
RUN uv sync --no-dev --no-install-project

# Install Playwright browsers (Chromium only)
RUN uv run playwright install chromium

# Copy source code
COPY src/ src/

# Install the project
RUN uv sync --no-dev

EXPOSE 3847

CMD ["uv", "run", "cinepyle"]
