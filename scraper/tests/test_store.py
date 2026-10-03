import json
from datetime import timedelta

import pytest

from scraper import store
from scraper.dedupe import item_id
from scraper.models import NewsFeed
from scraper.store import StoreError, load_existing, merge, write_feed

from conftest import NOW, make_item

WEEK = timedelta(days=7)


# --- merge ---


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


def test_stale_dated_item_still_in_feed_is_dropped():
    stale = make_item("s", NOW - timedelta(days=30))
    assert merge([stale], [stale], now=NOW, max_age=WEEK, max_items=10) == []


def test_merge_uses_fetched_at_when_no_published_date():
    undated = make_item("u", None, fetched_at=NOW)
    older = make_item("o", NOW - timedelta(days=1))

    merged = merge([], [older, undated], now=NOW, max_age=WEEK, max_items=10)

    assert [i.id for i in merged] == ["u", "o"]


def test_undated_item_does_not_flap_while_in_feed():
    """Simulate hourly runs: an undated item that stays in its feed must never reappear as new."""
    first_seen = NOW
    existing = []
    for hour in range(0, 24 * 10):
        now = first_seen + timedelta(hours=hour)
        fresh = [make_item("u", None, fetched_at=now)]
        existing = merge(existing, fresh, now=now, max_age=WEEK, max_items=10)
        [item] = existing
        assert item.fetched_at == first_seen, f"re-added as new at hour {hour}"


def test_undated_item_pruned_once_it_leaves_the_feed():
    item = make_item("u", None, fetched_at=NOW - timedelta(days=8))
    assert merge([item], [], now=NOW, max_age=WEEK, max_items=10) == []


# --- load_existing ---


def _write_raw(path, data):
    path.write_text(json.dumps(data))
    return path


def _raw_item(id, **overrides):
    raw = json.loads(make_item(id, NOW).model_dump_json())
    raw.update(overrides)
    return raw


def test_load_missing_returns_empty(tmp_path):
    assert load_existing(tmp_path / "missing.json") == []


@pytest.mark.parametrize(
    "content",
    [b"{not json", b"\xff\xfe\x00garbage", b'{"generated_at": "x"}', b'{"items": {}}', b"[]"],
)
def test_unreadable_file_raises_instead_of_wiping(tmp_path, content):
    path = tmp_path / "news.json"
    path.write_bytes(content)
    with pytest.raises(StoreError):
        load_existing(path)


def test_invalid_items_are_dropped_individually(tmp_path):
    path = _write_raw(
        tmp_path / "news.json",
        {
            "generated_at": NOW.isoformat(),
            "items": [_raw_item("good"), _raw_item("bad", title=None), _raw_item("js", url="javascript:x")],
        },
    )
    assert [i.url for i in load_existing(path)] == ["https://example.com/good"]


def test_ids_are_rederived_on_load(tmp_path):
    """An id from an older normalisation scheme must still dedupe against fresh items."""
    url = "http://example.com/post"
    path = _write_raw(
        tmp_path / "news.json",
        {"generated_at": NOW.isoformat(), "items": [_raw_item("stale-id-format", url=url)]},
    )
    [loaded] = load_existing(path)
    fresh = make_item(item_id("https://example.com/post"), NOW, url="https://example.com/post")

    assert loaded.id == fresh.id
    assert len(merge([loaded], [fresh], now=NOW, max_age=WEEK, max_items=10)) == 1


def test_naive_timestamps_are_read_as_utc_and_merge(tmp_path):
    path = _write_raw(
        tmp_path / "news.json",
        {
            "generated_at": "2026-10-03T11:00:00",
            "items": [_raw_item("a", published_at="2026-10-03T10:00:00", fetched_at="2026-10-03T10:30:00")],
        },
    )
    [item] = load_existing(path)
    assert item.published_at.tzinfo is not None

    merged = merge([item], [make_item("b", NOW)], now=NOW, max_age=WEEK, max_items=10)
    assert [i.url for i in merged] == ["https://example.com/b", "https://example.com/a"]


# --- write_feed ---


def test_write_then_load_roundtrip(tmp_path):
    path = tmp_path / "news.json"
    items = [make_item(item_id("https://example.com/a"), NOW, url="https://example.com/a")]

    write_feed(path, items, generated_at=NOW)

    feed = NewsFeed.model_validate_json(path.read_text())
    assert feed.generated_at == NOW
    assert load_existing(path) == items
    assert path.stat().st_mode & 0o777 == 0o644
    assert [p.name for p in tmp_path.iterdir()] == ["news.json"]


def test_write_requires_existing_directory(tmp_path):
    with pytest.raises(StoreError, match="does not exist"):
        write_feed(tmp_path / "nope" / "news.json", [], generated_at=NOW)
    assert not (tmp_path / "nope").exists()


def test_failed_write_leaves_no_temp_file_and_keeps_old(tmp_path, monkeypatch):
    path = tmp_path / "news.json"
    path.write_text("previous")

    def boom(*args):
        raise OSError("disk full")

    monkeypatch.setattr(store.os, "replace", boom)
    with pytest.raises(OSError):
        write_feed(path, [make_item("a", NOW)], generated_at=NOW)

    assert path.read_text() == "previous"
    assert [p.name for p in tmp_path.iterdir()] == ["news.json"]
