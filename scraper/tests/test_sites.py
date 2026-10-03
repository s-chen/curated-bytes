from datetime import timedelta

import requests

from scraper import sites
from scraper.models import Source
from scraper.sites import (
    SiteStats,
    format_report,
    load_stats,
    record_citations,
    save_stats,
    site_report,
    source_entry,
)

from conftest import NOW, make_item

SOURCES = [
    Source(id="hn", name="Hacker News", url="https://hnrss.org/frontpage", aggregator=True),
    Source(id="tc", name="TechCrunch", url="https://techcrunch.com/feed/"),
    Source(id="ars", name="Ars Technica", url="https://feeds.arstechnica.com/arstechnica/index"),
]


def _hn(n, url, **kw):
    return make_item(f"hn{n}", NOW, url=url, source_id="hn", source_name="Hacker News", **kw)


def _tc(n):
    return make_item(f"tc{n}", NOW, url=f"https://techcrunch.com/{n}", source_id="tc", title=f"TC story {n}")


def test_records_aggregator_and_article_citations_once_each():
    items = [_hn(1, "https://lwn.net/a"), _tc(1), _tc(2)]
    links = {"tc1": {"https://lwn.net/b", "https://lwn.net/c"}, "tc2": {"https://lwn.net/b"}}
    stats = record_citations(SiteStats(), items, links, {"hn"}, NOW)
    # Same inputs an hour later: nothing is double counted.
    stats = record_citations(stats, items, links, {"hn"}, NOW + timedelta(hours=1))
    assert len(stats.sites["lwn.net"]) == 4
    assert {c.source_id for c in stats.sites["lwn.net"].values()} == {"hn", "tc"}


def test_skips_aggregator_self_posts_and_prunes_old_citations():
    ask = _hn(1, "https://news.ycombinator.com/item?id=1", discussion_url="https://news.ycombinator.com/item?id=1")
    stats = record_citations(SiteStats(), [ask, _hn(2, "https://old.example/x")], {}, {"hn"}, NOW)
    assert list(stats.sites) == ["old.example"]
    later = record_citations(stats, [], {}, {"hn"}, NOW + timedelta(days=sites.STATS_DAYS))
    assert later.sites == {}


def test_stats_roundtrip_and_tolerate_bad_files(tmp_path):
    path = tmp_path / "state" / "site_stats.json"
    stats = record_citations(SiteStats(), [_hn(1, "https://lwn.net/a")], {}, {"hn"}, NOW)
    save_stats(path, stats)
    assert load_stats(path) == stats
    path.write_text("{bad")
    assert load_stats(path) == SiteStats()
    assert load_stats(tmp_path / "missing.json") == SiteStats()


def test_report_ranks_unfollowed_sites_by_citing_sources():
    items = [_tc(1), _tc(2), _tc(3)]
    links = {
        "tc1": {"https://lwn.net/1", "https://blog.example.org/1", "https://arstechnica.com/x"},
        "tc2": {"https://blog.example.org/2", "https://github.com/me/r", "https://twitter.com/x/1"},
        "tc3": {"https://blog.example.org/3"},
    }
    agg = [_hn(n, f"https://lwn.net/h{n}") for n in range(2)]
    stats = record_citations(SiteStats(), items + agg, links, {"hn"}, NOW)

    report = site_report(stats, items + agg, SOURCES, min_links=3)

    # lwn.net: 3 citations from 2 sources outranks blog.example.org: 3 from one source.
    # Ars is followed (by config), github is code hosting, twitter is social.
    assert [(s.host, s.links) for s in report] == [("lwn.net", 3), ("blog.example.org", 3)]
    assert report[0].citing_sources == {"Hacker News", "TechCrunch"}
    assert "TC story 1" in report[0].examples


class FakeResponse:
    def __init__(self, body=b"", status=200, content_type="text/html"):
        self.body = body
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.encoding = "utf-8"
        self.url = None
        self.text = body.decode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size):
        yield self.body


class FakeSession:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, **kwargs):
        return self.pages.get(url) or FakeResponse(status=404)


RSS = b"<rss version='2.0'><channel><title>LWN.net headlines</title><item><title>x</title><link>https://lwn.net/x</link></item></channel></rss>"


def test_finds_the_feed_a_homepage_advertises():
    session = FakeSession({
        "https://lwn.net/": FakeResponse(b"<html><head><link rel='alternate' type='application/rss+xml' href='/headlines/rss'></head></html>"),
        "https://lwn.net/headlines/rss": FakeResponse(RSS, content_type="application/rss+xml"),
    })
    assert sites.find_feed("lwn.net", session, sites._Robots(session)) == (
        "https://lwn.net/headlines/rss", "LWN.net headlines"
    )


def test_relative_feed_links_resolve_against_the_redirected_homepage():
    home = FakeResponse(b"<link rel='alternate' type='application/rss+xml' href='/feed'>")
    home.url = "https://www.blog.example/"
    session = FakeSession({
        "https://blog.example/": home,
        "https://www.blog.example/feed": FakeResponse(RSS, content_type="application/xml"),
    })
    assert sites.find_feed("blog.example", session, sites._Robots(session))[0] == "https://www.blog.example/feed"


def test_falls_back_to_common_feed_paths_and_gives_up_cleanly():
    session = FakeSession({"https://blog.example.org/feed.xml": FakeResponse(RSS, content_type="application/xml")})
    assert sites.find_feed("blog.example.org", session, sites._Robots(session))[0] == "https://blog.example.org/feed.xml"
    assert sites.find_feed("nothing.example", FakeSession({}), sites._Robots(FakeSession({}))) is None


def test_report_prints_ready_to_paste_entries():
    stat = sites.SiteStat(
        host="lwn.net", links=3, citing_sources={"TechCrunch"}, last_seen=NOW.date(),
        feed_checked=True, feed_url="https://lwn.net/headlines/rss", feed_title="LWN.net headlines",
    )
    missing = sites.SiteStat(host="blog.example.org", links=3, citing_sources={"X"}, last_seen=NOW.date(), feed_checked=True)
    text = format_report([stat, missing], SiteStats(), 3)
    assert 'feed: {"id": "lwn-net", "name": "LWN.net headlines", "url": "https://lwn.net/headlines/rss", "category": "tech", "weight": 1},' in text
    assert "feed: none found" in text
    assert source_entry(stat).startswith('{"id": "lwn-net"')
    assert "none yet" in format_report([], SiteStats(), 3)
