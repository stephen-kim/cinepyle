FROM python:3.14-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency specification first for layer caching
COPY pyproject.toml ./

# Install dependencies without the project itself
RUN uv sync --no-dev --no-install-project

# Copy source code
COPY src/ src/

# Install the project
RUN uv sync --no-dev

EXPOSE 8080

CMD ["uv", "run", "cinepyle"]
