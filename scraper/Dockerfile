# syntax=docker/dockerfile:1

FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN useradd --create-home --uid 1000 scraper

# Install dependencies first so code edits don't bust the layer cache.
COPY pyproject.toml ./
COPY src ./src
RUN pip install .

COPY config ./config
ENV NEWS_SOURCES=/app/config/news_sources.json \
    NEWS_OUTPUT=/data/news.json

# --- runtime: `docker compose run --rm scraper` ---
FROM base AS runtime
USER scraper
ENTRYPOINT ["python", "-m", "scraper"]

# --- test: `docker compose run --rm tests` ---
FROM base AS test
RUN pip install ".[dev]"
COPY tests ./tests
USER scraper
ENTRYPOINT ["python", "-m", "pytest", "-p", "no:cacheprovider"]
