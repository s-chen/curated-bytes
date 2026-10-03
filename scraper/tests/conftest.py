from datetime import datetime, timezone
from pathlib import Path

import pytest

from scraper.models import NewsItem, Source

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def source() -> Source:
    return Source(id="example", name="Example", url="https://example.com/feed")


@pytest.fixture
def rss_bytes() -> bytes:
    return (FIXTURES / "sample_rss.xml").read_bytes()


@pytest.fixture
def atom_bytes() -> bytes:
    return (FIXTURES / "sample_atom.xml").read_bytes()


def make_item(id: str, published_at: datetime | None = None, **overrides) -> NewsItem:
    fields = dict(
        id=id,
        title=f"Title {id}",
        url=f"https://example.com/{id}",
        source_id="example",
        source_name="Example",
        category="tech",
        published_at=published_at,
        fetched_at=NOW,
    )
    fields.update(overrides)
    return NewsItem(**fields)
