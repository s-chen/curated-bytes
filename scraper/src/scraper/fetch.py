"""Fetches RSS/Atom feeds and converts entries to `NewsItem`s."""

import logging
from calendar import timegm
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser

import feedparser
import requests

from scraper.dedupe import item_id
from scraper.models import NewsItem, Source

log = logging.getLogger(__name__)

USER_AGENT = "CuratedBytesBot/0.1 (+https://curatedbytes.dev)"
TIMEOUT_SECONDS = 15
SUMMARY_MAX_CHARS = 500


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def strip_html(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join(unescape("".join(parser.parts)).split())


def _truncate(text: str, limit: int = SUMMARY_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _entry_datetime(entry: feedparser.FeedParserDict) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc)


def parse_feed(content: bytes, source: Source, fetched_at: datetime) -> list[NewsItem]:
    """Convert raw feed bytes into `NewsItem`s, skipping entries without a title or link."""
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Unparseable feed: {feed.get('bozo_exception')}")

    items = []
    for entry in feed.entries:
        title = strip_html(entry.get("title", ""))
        link = entry.get("link", "").strip()
        if not title or not link:
            continue
        summary = strip_html(entry.get("summary", ""))
        items.append(
            NewsItem(
                id=item_id(link),
                title=title,
                url=link,
                source_id=source.id,
                source_name=source.name,
                category=source.category,
                summary=_truncate(summary) or None,
                published_at=_entry_datetime(entry),
                fetched_at=fetched_at,
            )
        )
    return items


def fetch_source(
    source: Source, fetched_at: datetime, session: requests.Session | None = None
) -> list[NewsItem]:
    http = session or requests
    response = http.get(
        str(source.url), headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return parse_feed(response.content, source, fetched_at)


def fetch_all(
    sources: list[Source], fetched_at: datetime, max_workers: int = 8
) -> tuple[list[NewsItem], list[str]]:
    """Fetch all sources concurrently.

    A failing source is logged and skipped. Returns the items and the ids of failed sources.
    """
    items: list[NewsItem] = []
    failed: list[str] = []

    with requests.Session() as session, ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_source, s, fetched_at, session): s for s in sources}
        for future, source in futures.items():
            try:
                source_items = future.result()
            except Exception as exc:  # one bad feed must not sink the run
                log.warning("Failed to fetch %s (%s): %s", source.id, source.url, exc)
                failed.append(source.id)
                continue
            log.info("Fetched %d items from %s", len(source_items), source.id)
            items.extend(source_items)

    return items, failed
