from datetime import timedelta

from scraper.models import Source
from scraper.sites import format_report, site_report

from conftest import NOW, make_item

SOURCES = [
    Source(id="hn", name="Hacker News", url="https://hnrss.org/frontpage", aggregator=True),
    Source(id="lob", name="Lobsters", url="https://lobste.rs/rss", aggregator=True),
    Source(id="ars", name="Ars Technica", url="https://feeds.arstechnica.com/arstechnica/index"),
]


def _link(n, url, source="hn", points=None, **kw):
    name = {"hn": "Hacker News", "lob": "Lobsters"}.get(source, source)
    return make_item(f"{source}{n}", NOW - timedelta(hours=n), url=url, source_id=source,
                     source_name=name, points=points, **kw)


def test_counts_unfollowed_sites_linked_by_aggregators():
    items = [
        _link(1, "https://www.lwn.net/a", points=100),
        _link(2, "https://lwn.net/b", points=300, title="Big LWN story"),
        _link(3, "https://lwn.net/c", source="lob"),
        _link(4, "https://blog.example.org/x"),
        _link(5, "https://blog.example.org/y"),
        _link(6, "https://blog.example.org/z"),
        _link(7, "https://rare.example/one"),
    ]
    [lwn, blog] = site_report(items, SOURCES, min_links=3)

    assert (lwn.host, lwn.links, lwn.aggregators, lwn.points) == (
        "lwn.net", 3, {"Hacker News", "Lobsters"}, 400
    )
    assert lwn.examples[0].title == "Big LWN story"  # most points first
    assert (blog.host, blog.links) == ("blog.example.org", 3)


def test_skips_followed_sites_code_hosts_and_self_posts():
    items = [
        # Ars is followed: its own items publish on arstechnica.com.
        make_item("ars1", NOW, url="https://arstechnica.com/story", source_id="ars"),
        *[_link(n, f"https://arstechnica.com/s{n}") for n in range(3)],
        *[_link(n + 10, f"https://github.com/me/repo{n}") for n in range(3)],
        *[
            _link(n + 20, f"https://news.ycombinator.com/item?id={n}",
                  discussion_url=f"https://news.ycombinator.com/item?id={n}")
            for n in range(3)
        ],
        # Non-aggregator sources never count, whatever they link to.
        *[make_item(f"x{n}", NOW, url=f"https://elsewhere.example/{n}", source_id="other") for n in range(3)],
    ]
    assert site_report(items, SOURCES, min_links=1) == []


def test_format_report():
    items = [_link(n, f"https://lwn.net/{n}", points=10) for n in range(3)]
    text = format_report(site_report(items, SOURCES), items, 3)
    assert "at least 3 times" in text
    assert "lwn.net  3 links via Hacker News, 30 points" in text
    assert "e.g. Title hn0" in text
    assert "none" in format_report([], [], 3)
