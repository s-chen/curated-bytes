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

from scraper.dedupe import item_id
from scraper.models import NewsFeed, NewsItem, TopStory

log = logging.getLogger(__name__)


class StoreError(Exception):
    """The existing news.json can't be read. Raised instead of silently discarding history."""


def load_existing(path: Path) -> list[NewsItem]:
    """Load items from a previous run.

    A missing file means a first run. Individual invalid items are dropped with a warning.
    Raises `StoreError` if the file as a whole is unreadable, so the caller can stop rather
    than overwrite it.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
        raw_items = data["items"]
        if not isinstance(raw_items, list):
            raise TypeError("'items' is not a list")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise StoreError(f"Can't read {path}: {exc!r}") from exc

    items = []
    for index, raw in enumerate(raw_items):
        try:
            item = NewsItem.model_validate(raw)
            # Re-derive the id so changes to URL normalisation don't create duplicates.
            items.append(item.model_copy(update={"id": item_id(item.url)}))
        except (ValidationError, ValueError) as exc:
            reason = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else exc
            log.warning("Dropping invalid item %d from %s: %s", index, path, reason)
    return items


def _sort_key(item: NewsItem) -> datetime:
    return item.published_at or item.fetched_at


def merge(
    existing: list[NewsItem],
    fresh: list[NewsItem],
    now: datetime,
    max_age: timedelta,
    max_items: int,
) -> list[NewsItem]:
    """Dedupe by id, drop items older than `max_age`, sort newest first, cap at `max_items`.

    An item already in `existing` keeps its original `fetched_at` (and review and score),
    but takes the fresh copy's discussion counts. Undated items are aged by
    `fetched_at`, so one that is still in its feed is kept past `max_age`. Otherwise it would
    be pruned and then re-fetched as new on the next run.
    """
    fresh_ids = {item.id for item in fresh}
    by_id: dict[str, NewsItem] = {}
    for item in [*existing, *fresh]:
        kept = by_id.setdefault(item.id, item)
        if kept is not item and item.discussion_url:
            # Discussion counts grow between runs: take the latest, keep everything else. The
            # summary too, as aggregator summaries are mostly the boilerplate those come from.
            by_id[item.id] = kept.model_copy(
                update={
                    "summary": item.summary,
                    "discussion_url": item.discussion_url,
                    "points": item.points,
                    "comments": item.comments,
                }
            )

    cutoff = now - max_age

    def keep(item: NewsItem) -> bool:
        if _sort_key(item) >= cutoff:
            return True
        return item.published_at is None and item.id in fresh_ids

    kept = [i for i in by_id.values() if keep(i)]
    kept.sort(key=_sort_key, reverse=True)
    return kept[:max_items]


def write_feed(
    path: Path,
    items: list[NewsItem],
    generated_at: datetime,
    top_stories: list[TopStory] | None = None,
) -> None:
    """Write atomically so the dashboard never reads a half-written file.

    The parent directory must already exist: a wrong path should fail, not create
    directories somewhere unexpected.
    """
    if not path.parent.is_dir():
        raise StoreError(f"Output directory does not exist: {path.parent}")
    feed = NewsFeed(generated_at=generated_at, items=items, top_stories=top_stories or [])
    payload = feed.model_dump_json(indent=2)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
        try:
            tmp.write(payload + "\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        except BaseException:
            tmp.close()
            tmp_path.unlink(missing_ok=True)
            raise
    try:
        os.chmod(tmp_path, 0o644)  # NamedTemporaryFile is 0600; the site needs it world-readable
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
