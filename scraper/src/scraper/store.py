"""Reads and writes `news.json`, merging new items with the previous run.

The previous `news.json` is the dedupe state: there is no database.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from scraper.models import NewsFeed, NewsItem

log = logging.getLogger(__name__)


def load_existing(path: Path) -> list[NewsItem]:
    if not path.exists():
        return []
    try:
        return NewsFeed.model_validate_json(path.read_text(encoding="utf-8")).items
    except (ValidationError, json.JSONDecodeError) as exc:
        log.warning("Ignoring unreadable %s: %s", path, exc)
        return []


def merge(
    existing: list[NewsItem],
    fresh: list[NewsItem],
    now: datetime,
    max_age: timedelta,
    max_items: int,
) -> list[NewsItem]:
    """Dedupe by id, drop items older than `max_age`, sort newest first, cap at `max_items`.

    An item already in `existing` keeps its original `fetched_at`.
    """
    by_id: dict[str, NewsItem] = {}
    for item in [*existing, *fresh]:
        by_id.setdefault(item.id, item)

    cutoff = now - max_age

    def sort_key(item: NewsItem) -> datetime:
        return item.published_at or item.fetched_at

    kept = [i for i in by_id.values() if sort_key(i) >= cutoff]
    kept.sort(key=sort_key, reverse=True)
    return kept[:max_items]


def write_feed(path: Path, items: list[NewsItem], generated_at: datetime) -> None:
    """Write atomically so the dashboard never reads a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = NewsFeed(generated_at=generated_at, items=items).model_dump_json(indent=2)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
    ) as tmp:
        tmp.write(payload + "\n")
    os.chmod(tmp.name, 0o644)  # NamedTemporaryFile is 0600; the site needs it world-readable
    os.replace(tmp.name, path)
