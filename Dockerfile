FROM python:3.14-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency specification first for layer caching
COPY pyproject.toml ./

# Install dependencies without the project itself
RUN uv sync --no-dev --no-install-project

# Copy source code, seed data, and assets
COPY src/ src/
COPY seed/ seed/
COPY asset/ asset/

# Install the project
RUN uv sync --no-dev

# Install Playwright Chromium and its system dependencies
RUN uv run playwright install --with-deps chromium

EXPOSE ${DASHBOARD_PORT:-3847}

CMD ["uv", "run", "cinepyle"]
