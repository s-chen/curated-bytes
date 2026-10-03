from datetime import datetime, timezone

import pytest
import requests

from scraper import fetch
from scraper.dedupe import item_id
from scraper.models import Source

from conftest import NOW


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


def test_parse_garbage_raises(source):
    with pytest.raises(ValueError, match="Unparseable"):
        fetch.parse_feed(b"<<<not xml", source, NOW)


def test_long_summary_is_truncated():
    text = "word " * 200
    out = fetch._truncate(text.strip(), limit=50)
    assert len(out) <= 51
    assert out.endswith("…")


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


def test_fetch_source_sends_user_agent_and_timeout(source, rss_bytes):
    calls = {}

    class FakeResponse:
        content = rss_bytes

        def raise_for_status(self):
            pass

    class FakeSession:
        def get(self, url, headers, timeout):
            calls.update(url=url, headers=headers, timeout=timeout)
            return FakeResponse()

    items = fetch.fetch_source(source, NOW, session=FakeSession())

    assert len(items) == 2
    assert calls["url"] == "https://example.com/feed"
    assert "CuratedBytes" in calls["headers"]["User-Agent"]
    assert calls["timeout"] == fetch.TIMEOUT_SECONDS
