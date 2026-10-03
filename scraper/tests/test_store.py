from datetime import timedelta

from scraper.models import NewsFeed
from scraper.store import load_existing, merge, write_feed

from conftest import NOW, make_item

WEEK = timedelta(days=7)


def test_merge_dedupes_and_keeps_existing_copy():
    old = make_item("a", NOW - timedelta(hours=2), fetched_at=NOW - timedelta(hours=1))
    dup = make_item("a", NOW - timedelta(hours=2))
    new = make_item("b", NOW - timedelta(hours=1))

    merged = merge([old], [dup, new], now=NOW, max_age=WEEK, max_items=100)

    assert [i.id for i in merged] == ["b", "a"]
    assert merged[1].fetched_at == NOW - timedelta(hours=1)


def test_merge_drops_stale_items_and_caps():
    items = [make_item(str(n), NOW - timedelta(days=n)) for n in range(10)]

    merged = merge([], items, now=NOW, max_age=WEEK, max_items=5)

    assert [i.id for i in merged] == ["0", "1", "2", "3", "4"]
    assert all(i.published_at >= NOW - WEEK for i in merged)


def test_merge_uses_fetched_at_when_no_published_date():
    undated = make_item("u", None, fetched_at=NOW)
    older = make_item("o", NOW - timedelta(days=1))

    merged = merge([], [older, undated], now=NOW, max_age=WEEK, max_items=10)

    assert [i.id for i in merged] == ["u", "o"]


def test_write_then_load_roundtrip(tmp_path):
    path = tmp_path / "public" / "news.json"
    items = [make_item("a", NOW)]

    write_feed(path, items, generated_at=NOW)

    feed = NewsFeed.model_validate_json(path.read_text())
    assert feed.generated_at == NOW
    assert load_existing(path) == items
    assert list(path.parent.glob("*.tmp")) == []
    assert path.stat().st_mode & 0o777 == 0o644


def test_load_missing_or_corrupt_returns_empty(tmp_path):
    assert load_existing(tmp_path / "missing.json") == []

    corrupt = tmp_path / "news.json"
    corrupt.write_text("{not json")
    assert load_existing(corrupt) == []
