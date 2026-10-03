"""Pydantic models.

`NewsItem` and `NewsFeed` define the `news.json` contract. Keep them in sync with
the `NewsItem` TypeScript interface in `web-dashboard/src/App.tsx`.
"""

from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, Field, HttpUrl, field_validator


def _as_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC so aware and naive values never get compared."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


class Source(BaseModel):
    """One entry in `config/news_sources.json`."""

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    url: HttpUrl
    category: str = "tech"
    enabled: bool = True


class SourcesConfig(BaseModel):
    sources: list[Source]


class NewsItem(BaseModel):
    id: str  # MD5 of the normalised URL
    title: str = Field(min_length=1)
    url: str  # absolute http(s) only: rendered as a link by the dashboard
    source_id: str
    source_name: str
    category: str
    summary: str | None = None
    published_at: UtcDatetime | None = None
    fetched_at: UtcDatetime

    @field_validator("url")
    @classmethod
    def _http_url_only(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ValueError("url must be an absolute http(s) URL")
        return value


class NewsFeed(BaseModel):
    """Top-level shape of `news.json`."""

    generated_at: UtcDatetime
    items: list[NewsItem]
