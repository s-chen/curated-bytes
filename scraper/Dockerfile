# syntax=docker/dockerfile:1

FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src
WORKDIR /app
RUN useradd --create-home --uid 1000 scraper \
    && mkdir /data && chown scraper /data

# Install dependencies (read from pyproject.toml) in their own layer, so code edits
# don't reinstall them. The package itself runs from /app/src via PYTHONPATH.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY config ./config
COPY src ./src
ENV NEWS_SOURCES=/app/config/news_sources.json \
    NEWS_OUTPUT=/data/news.json

# --- runtime: `docker compose run --rm scraper` ---
FROM base AS runtime
USER scraper
ENTRYPOINT ["python", "-m", "scraper"]

# --- test: `docker compose run --rm tests` ---
FROM base AS test
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['optional-dependencies']['dev']))" > /tmp/requirements-dev.txt \
    && pip install -r /tmp/requirements-dev.txt
COPY tests ./tests
USER scraper
ENTRYPOINT ["python", "-m", "pytest", "-p", "no:cacheprovider"]
