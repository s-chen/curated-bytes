from datetime import datetime, timedelta, timezone

import pytest
import requests

from scraper import fetch
from scraper.dedupe import item_id
from scraper.models import Source

from conftest import NOW


def rss(*items: str) -> bytes:
    """Build a minimal RSS document from raw <item> bodies."""
    body = "".join(f"<item>{i}</item>" for i in items)
    return f'<rss version="2.0"><channel><title>t</title>{body}</channel></rss>'.encode()


def test_parse_rss(rss_bytes, source):
    items = fetch.parse_feed(rss_bytes, source, NOW)

    # The entry with an empty title is skipped.
    assert [i.title for i in items] == ["Rust 2.0 & the future", "No date item"]

    rust = items[0]
    assert rust.id == item_id("https://example.com/rust-2")
    assert rust.summary == "The Rust team announces things."
    assert rust.published_at == datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    assert rust.source_id == "example"
    assert rust.fetched_at == NOW

    assert items[1].published_at is None
    assert items[1].summary is None


def test_parse_atom(atom_bytes, source):
    [item] = fetch.parse_feed(atom_bytes, source, NOW)
    assert item.title == "Kernel 7.0 released"
    assert item.url == "https://example.org/kernel-7"
    assert item.published_at == datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


# --- text handling ---


@pytest.mark.parametrize(
    "html, text",
    [
        ("AT&T", "AT&T"),
        ("Q&A", "Q&A"),
        ("R&amp;D", "R&D"),
        ("<p>Hello <b>world</b></p>", "Hello world"),
        ("before<script>alert(1)</script><style>p{}</style>after", "beforeafter"),
        ("&amp;lt;script&amp;gt;", "&lt;script&gt;"),  # decoded once, not twice
        ("  lots \n of\tspace ", "lots of space"),
    ],
)
def test_strip_html(html, text):
    assert fetch.strip_html(html) == text


@pytest.mark.parametrize(
    "title_xml, expected",
    [
        ("AT&amp;T buys Q&amp;A site", "AT&T buys Q&A site"),
        ("Understanding &lt;div&gt; elements", "Understanding <div> elements"),
        ("x &lt;y and done", "x <y and done"),
    ],
)
def test_plain_text_titles_are_not_html_stripped(source, title_xml, expected):
    [item] = fetch.parse_feed(rss(f"<title>{title_xml}</title><link>https://x.com/a</link>"), source, NOW)
    assert item.title == expected


def test_html_typed_atom_title_is_stripped(source):
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>
      <entry><title type="html">&lt;b&gt;Bold&lt;/b&gt; &amp;amp; co</title>
      <link href="https://x.com/a"/><id>1</id></entry></feed>"""
    [item] = fetch.parse_feed(atom, source, NOW)
    assert item.title == "Bold & co"


def test_long_summary_is_truncated():
    text = "word " * 200
    out = fetch._truncate(text.strip(), limit=50)
    assert len(out) <= 51
    assert out.endswith("…")


# --- links ---


@pytest.mark.parametrize(
    "link",
    [
        "javascript:alert(document.cookie)",
        "JaVaScRiPt:alert(1)",
        "data:text/html,&lt;script&gt;alert(1)&lt;/script&gt;",
        "ftp://example.com/file",
        "mailto:someone@example.com",
    ],
)
def test_unsafe_link_schemes_are_dropped(source, link):
    feed = rss(
        f"<title>bad</title><link>{link}</link>",
        "<title>good</title><link>https://x.com/good</link>",
    )
    assert [i.title for i in fetch.parse_feed(feed, source, NOW)] == ["good"]


def test_unsafe_atom_link_is_dropped(source):
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>
      <entry><title>bad</title><link href="javascript:alert(1)"/><id>1</id></entry>
      <entry><title>good</title><link href="https://x.com/good"/><id>2</id></entry></feed>"""
    assert [i.title for i in fetch.parse_feed(atom, source, NOW)] == ["good"]


def test_relative_link_resolved_against_feed_url(source):
    feed = rss("<title>rel</title><link>/posts/1</link>")
    [item] = fetch.parse_feed(feed, source, NOW, base_url="https://blog.example/feed/")
    assert item.url == "https://blog.example/posts/1"


def test_malformed_link_skips_only_that_entry(source):
    feed = rss(
        "<title>broken</title><link>http://[::1/broken</link>",
        "<title>fine</title><link>https://x.com/fine</link>",
    )
    assert [i.title for i in fetch.parse_feed(feed, source, NOW)] == ["fine"]


# --- dates ---


def test_future_dates_are_clamped_to_fetch_time(source):
    feed = rss("<title>t</title><link>https://x.com/a</link><pubDate>Fri, 01 Jan 2027 00:00:00 GMT</pubDate>")
    [item] = fetch.parse_feed(feed, source, NOW)
    assert item.published_at == NOW


# --- unusable content ---


def test_parse_garbage_raises(source):
    with pytest.raises(fetch.FeedError):
        fetch.parse_feed(b"<<<not xml", source, NOW)


def test_feed_with_no_entries_raises(source):
    with pytest.raises(fetch.FeedError, match="no entries"):
        fetch.parse_feed(b"<html><body>Checking your browser...</body></html>", source, NOW)


def test_body_is_never_treated_as_a_local_path(tmp_path, source, rss_bytes):
    local_feed = tmp_path / "feed.xml"
    local_feed.write_bytes(rss_bytes)
    # If feedparser opened this as a path it would find a valid feed.
    with pytest.raises(fetch.FeedError):
        fetch.parse_feed(str(local_feed).encode(), source, NOW)


# --- downloading ---


class FakeResponse:
    def __init__(self, chunks, headers=None, url="https://example.com/feed"):
        self._chunks = chunks
        self.headers = headers or {}
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield from self._chunks


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = {}

    def get(self, url, **kwargs):
        self.calls = dict(url=url, **kwargs)
        return self.response


def test_fetch_source_request_options(source, rss_bytes):
    session = FakeSession(FakeResponse([rss_bytes]))

    items = fetch.fetch_source(source, NOW, session=session)

    assert len(items) == 2
    assert session.calls["url"] == "https://example.com/feed"
    assert "CuratedBytes" in session.calls["headers"]["User-Agent"]
    assert session.calls["timeout"] == fetch.TIMEOUT_SECONDS
    assert session.calls["stream"] is True


def test_fetch_source_resolves_links_against_final_url(source):
    response = FakeResponse(
        [rss("<title>rel</title><link>/a</link>")], url="https://moved.example/rss"
    )
    [item] = fetch.fetch_source(source, NOW, session=FakeSession(response))
    assert item.url == "https://moved.example/a"


def test_declared_oversize_feed_rejected(source, monkeypatch):
    monkeypatch.setattr(fetch, "MAX_FEED_BYTES", 10)
    response = FakeResponse([b"x"], headers={"Content-Length": "11"})
    with pytest.raises(fetch.FeedError, match="too large"):
        fetch.fetch_source(source, NOW, session=FakeSession(response))


def test_streamed_oversize_feed_rejected(source, monkeypatch):
    monkeypatch.setattr(fetch, "MAX_FEED_BYTES", 10)
    response = FakeResponse([b"x" * 6, b"x" * 6])  # no Content-Length
    with pytest.raises(fetch.FeedError, match="larger than"):
        fetch.fetch_source(source, NOW, session=FakeSession(response))


def test_slow_feed_hits_total_deadline(source, monkeypatch):
    clock = iter(range(0, 1000, 10))  # every call to monotonic() advances 10s
    monkeypatch.setattr(fetch.time, "monotonic", lambda: next(clock))
    response = FakeResponse([b"x"] * 100)
    with pytest.raises(fetch.FeedError, match="exceeded"):
        fetch.fetch_source(source, NOW, session=FakeSession(response))


def test_fetch_all_skips_failing_sources(monkeypatch, rss_bytes):
    good = Source(id="good", name="Good", url="https://good.example/feed")
    bad = Source(id="bad", name="Bad", url="https://bad.example/feed")

    def fake_fetch_source(src, fetched_at, session=None):
        if src.id == "bad":
            raise requests.ConnectionError("boom")
        return fetch.parse_feed(rss_bytes, src, fetched_at)

    monkeypatch.setattr(fetch, "fetch_source", fake_fetch_source)
    items, failed = fetch.fetch_all([good, bad], NOW)

    assert failed == ["bad"]
    assert {i.source_id for i in items} == {"good"}
    assert len(items) == 2


def test_items_are_dated_no_later_than_fetch(source, rss_bytes):
    later = NOW + timedelta(days=365)
    assert all(
        i.published_at is None or i.published_at <= later
        for i in fetch.parse_feed(rss_bytes, source, later)
    )
