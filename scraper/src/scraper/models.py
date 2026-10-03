"""Pydantic models.

`NewsItem` and `NewsFeed` define the `news.json` contract. Keep them in sync with
the `NewsItem` TypeScript interface in `web-dashboard/src/App.tsx`.
"""

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


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
    title: str
    url: str
    source_id: str
    source_name: str
    category: str
    summary: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime


class NewsFeed(BaseModel):
    """Top-level shape of `news.json`."""

    generated_at: datetime
    items: list[NewsItem]
