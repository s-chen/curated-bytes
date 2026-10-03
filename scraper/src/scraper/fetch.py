"""Fetches RSS/Atom feeds and converts entries to `NewsItem`s."""

import io
import logging
import re
import time
from calendar import timegm
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import feedparser
import requests

from scraper.dedupe import item_id
from scraper.models import NewsItem, Source

log = logging.getLogger(__name__)

USER_AGENT = "CuratedBytesBot/0.1 (+https://curatedbytes.dev)"
TIMEOUT_SECONDS = 15  # connect timeout, and max wait between bytes
DEADLINE_SECONDS = 30  # max total time to download one feed
MAX_FEED_BYTES = 5 * 1024 * 1024
SUMMARY_MAX_CHARS = 500
ALLOWED_SCHEMES = {"http", "https"}


class FeedError(Exception):
    """A feed could not be downloaded or parsed."""


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def strip_html(html: str) -> str:
    """Return the visible text of an HTML fragment. Entities are decoded exactly once."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()  # flushes text held back while waiting for a possible entity
    return collapse_whitespace("".join(parser.parts))


def _entry_text(entry: feedparser.FeedParserDict, field: str) -> str:
    """Plain text for `title`/`summary`, stripping markup only when the feed says it's HTML."""
    value = entry.get(field) or ""
    content_type = (entry.get(f"{field}_detail") or {}).get("type", "text/plain")
    return strip_html(value) if "html" in content_type else collapse_whitespace(value)


def _truncate(text: str, limit: int = SUMMARY_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def safe_link(link: str, base_url: str | None) -> str | None:
    """Resolve `link` against the feed URL. Returns None unless it's an absolute http(s) URL."""
    link = link.strip()
    if not link:
        return None
    resolved = urljoin(base_url, link) if base_url else link
    parts = urlsplit(resolved)
    if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.hostname:
        return None
    return resolved


def _entry_datetime(entry: feedparser.FeedParserDict, fetched_at: datetime) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    # Clamp future dates so a mis-dated entry can't pin itself to the top.
    return min(datetime.fromtimestamp(timegm(parsed), tz=timezone.utc), fetched_at)


# Aggregator boilerplate in summaries, e.g. hnrss: "Article URL: … Comments URL: … Points: 6
# # Comments: 0", and Lobsters: a lone "Comments" link.
_POINTS = re.compile(r"\bPoints:\s*(\d+)")
_COMMENTS = re.compile(r"#\s*Comments:\s*(\d+)")
_BOILERPLATE = re.compile(
    r"(Article URL|Comments URL):\s*\S+|\bPoints:\s*\d+|#\s*Comments:\s*\d+|^\s*Comments\s*$"
)


def discussion_stats(summary: str) -> tuple[str, int | None, int | None]:
    """Split aggregator boilerplate out of a summary: (clean summary, points, comments)."""
    points = _POINTS.search(summary)
    comments = _COMMENTS.search(summary)
    clean = collapse_whitespace(_BOILERPLATE.sub(" ", summary))
    return (
        clean,
        int(points.group(1)) if points else None,
        int(comments.group(1)) if comments else None,
    )


def _to_item(
    entry: feedparser.FeedParserDict, source: Source, fetched_at: datetime, base_url: str | None
) -> NewsItem | None:
    title = _entry_text(entry, "title")
    link = safe_link(entry.get("link", ""), base_url)
    if not title or not link:
        return None
    summary, points, comments = discussion_stats(_entry_text(entry, "summary"))
    return NewsItem(
        id=item_id(link),
        title=title,
        url=link,
        source_id=source.id,
        source_name=source.name,
        category=source.category,
        summary=_truncate(summary) or None,
        published_at=_entry_datetime(entry, fetched_at),
        fetched_at=fetched_at,
        discussion_url=safe_link(entry.get("comments", ""), base_url),
        points=points,
        comments=comments,
    )


def parse_feed(
    content: bytes, source: Source, fetched_at: datetime, base_url: str | None = None
) -> list[NewsItem]:
    """Convert raw feed bytes into `NewsItem`s.

    Entries without a title or a safe http(s) link are skipped, and so is any entry that
    fails to convert. Raises `FeedError` if the content has no entries at all.
    """
    base_url = base_url or str(source.url)
    # Wrap in BytesIO: given bytes, feedparser first tries to open them as a local path.
    feed = feedparser.parse(
        io.BytesIO(content), response_headers={"content-location": base_url}
    )
    if not feed.entries:
        detail = f" (parser: {feed.bozo_exception})" if feed.get("bozo_exception") else ""
        raise FeedError(f"Not a usable feed: no entries{detail}")

    items = []
    for entry in feed.entries:
        try:
            item = _to_item(entry, source, fetched_at, base_url)
        except Exception as exc:  # one malformed entry must not sink the source
            log.warning("Skipping bad entry in %s (%r): %s", source.id, entry.get("link"), exc)
            continue
        if item is None:
            log.debug("Skipping entry without title/safe link in %s: %r", source.id, entry.get("link"))
            continue
        items.append(item)
    return items


def _download(url: str, session: requests.Session) -> tuple[bytes, str]:
    """GET `url` with a total deadline and size cap. Returns (body, final URL after redirects)."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    with session.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS, stream=True
    ) as response:
        response.raise_for_status()
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_FEED_BYTES:
            raise FeedError(f"Feed too large: {declared} bytes")

        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            body += chunk
            if len(body) > MAX_FEED_BYTES:
                raise FeedError(f"Feed larger than {MAX_FEED_BYTES} bytes")
            if time.monotonic() > deadline:
                raise FeedError(f"Download exceeded {DEADLINE_SECONDS}s")
        return bytes(body), response.url or url


def fetch_source(
    source: Source, fetched_at: datetime, session: requests.Session | None = None
) -> list[NewsItem]:
    if session is None:
        with requests.Session() as own_session:
            return fetch_source(source, fetched_at, own_session)
    content, final_url = _download(str(source.url), session)
    return parse_feed(content, source, fetched_at, base_url=final_url)


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
