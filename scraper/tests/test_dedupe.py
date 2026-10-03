import pytest

from scraper.dedupe import item_id, normalise_url


@pytest.mark.parametrize(
    "a, b",
    [
        ("https://Example.com/post/", "https://example.com/post"),
        ("https://example.com/post#comments", "https://example.com/post"),
        ("https://example.com/post?utm_source=rss&utm_medium=feed", "https://example.com/post"),
        ("https://example.com/post?fbclid=abc", "https://example.com/post"),
        ("  https://example.com/post  ", "https://example.com/post"),
        ("https://example.com:443/post", "https://example.com/post"),
        ("http://example.com:80/post", "https://example.com/post"),
        ("http://example.com/post", "https://example.com/post"),
        ("https://example.com/p?b=2&a=1", "https://example.com/p?a=1&b=2"),
    ],
)
def test_equivalent_urls_share_an_id(a, b):
    assert item_id(a) == item_id(b)


@pytest.mark.parametrize(
    "a, b",
    [
        ("https://example.com/item?id=1", "https://example.com/item?id=2"),
        # `ref` is meaningful on e.g. GitHub (branch/tag), so it is not treated as tracking.
        ("https://github.com/o/r/blob/x?ref=v1", "https://github.com/o/r/blob/x?ref=v2"),
        ("https://example.com:8443/post", "https://example.com/post"),
    ],
)
def test_distinct_urls_get_distinct_ids(a, b):
    assert item_id(a) != item_id(b)


def test_meaningful_query_params_are_kept():
    assert normalise_url("https://example.com/item?id=42&utm_source=x") == (
        "https://example.com/item?id=42"
    )


def test_id_is_md5_hex():
    assert len(item_id("https://example.com")) == 32
