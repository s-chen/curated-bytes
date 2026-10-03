import pytest

from scraper.dedupe import item_id, normalise_url


@pytest.mark.parametrize(
    "a, b",
    [
        ("https://Example.com/post/", "https://example.com/post"),
        ("https://example.com/post#comments", "https://example.com/post"),
        ("https://example.com/post?utm_source=rss&utm_medium=feed", "https://example.com/post"),
        ("https://example.com/post?ref=hn", "https://example.com/post"),
        ("  https://example.com/post  ", "https://example.com/post"),
    ],
)
def test_equivalent_urls_share_an_id(a, b):
    assert item_id(a) == item_id(b)


def test_meaningful_query_params_are_kept():
    assert normalise_url("https://example.com/item?id=42&utm_source=x") == (
        "https://example.com/item?id=42"
    )
    assert item_id("https://example.com/item?id=1") != item_id("https://example.com/item?id=2")


def test_id_is_md5_hex():
    assert len(item_id("https://example.com")) == 32
