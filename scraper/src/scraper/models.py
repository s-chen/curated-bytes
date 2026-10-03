"""Pydantic models.

`NewsItem`, `TopStory` and `NewsFeed` define the `news.json` contract. Keep them in sync
with the TypeScript interfaces in `web-dashboard/src/App.tsx`.
"""

from datetime import datetime, timezone
from typing import Annotated, Literal
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
    # How much coverage from this source counts towards a top story: 3 for major outlets,
    # 1 for small sites and niche blogs.
    weight: int = Field(default=1, ge=1, le=3)
    # Links to other sites' articles (Hacker News, Lobsters): used by the site report.
    aggregator: bool = False
    # A company engineering blog: its posts rank first on the dashboard.
    engineering: bool = False
    enabled: bool = True


class SourcesConfig(BaseModel):
    sources: list[Source]


# "pending" until reviewed; only "kept" items are shown on the dashboard.
Review = Literal["pending", "kept", "excluded"]


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
    # Discussion thread (e.g. on Hacker News or Lobsters) and its activity, when the feed has it.
    discussion_url: str | None = None
    points: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    engineering: bool = False  # from an engineering blog (set from the sources config each run)
    review: Review = "pending"
    # Gemini's 1-5 importance score; orders the dashboard list. None until scored.
    importance: int | None = Field(default=None, ge=1, le=5)

    @field_validator("url", "discussion_url")
    @classmethod
    def _http_url_only(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ValueError("url must be an absolute http(s) URL")
        return value


class TopStory(BaseModel):
    """A top story: an event covered by several sources (grouped and summarised by Gemini),
    or on quiet days a standout single-source story."""

    id: str  # id of the lead item
    title: str = Field(min_length=1)
    summary: str | None = None
    why_it_matters: str | None = None  # one sentence for software engineers, from Gemini
    item_ids: list[str] = Field(min_length=1)  # lead first; all present in `NewsFeed.items`


class NewsFeed(BaseModel):
    """Top-level shape of `news.json`."""

    generated_at: UtcDatetime
    items: list[NewsItem]
    top_stories: list[TopStory] = []
