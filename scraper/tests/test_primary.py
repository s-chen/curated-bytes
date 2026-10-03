import requests

from scraper import primary
from scraper.models import TopStory
from scraper.primary import choose_primary, extract_links, find_primary_sources, site_key

from conftest import NOW, make_item

ARTICLE = """
<html><header><a href="https://techcrunch.com/">Home</a><a href="https://x.com/techcrunch">X</a></header>
<nav><a href="https://developer.apple.com/nav-link">nav</a></nav>
<article>
  <p>Apple <a href="https://developer.apple.com/news/?id=p6zjojqw&utm_source=tc">announced</a>
  changes, as <a href="/2026/10/01/earlier-story/">we reported</a> and
  <a href="https://www.theverge.com/tech/1004295">The Verge</a> noted.
  <a href="https://twitter.com/apple/status/1">tweet</a>
  <a href="mailto:tips@techcrunch.com">tips</a>
  <a href="https://en.wikipedia.org/wiki/macOS">macOS</a>
  <a href="https://example.org/">a homepage</a></p>
</article>
<aside><a href="https://sponsor.example/deal">ad</a></aside>
<footer><a href="https://about.example/x">footer</a></footer></html>
"""


def test_site_key():
    assert site_key("www.techcrunch.com") == "techcrunch.com"
    assert site_key("feeds.arstechnica.com") == "arstechnica.com"
    assert site_key("news.bbc.co.uk") == "bbc.co.uk"


def test_extract_links_keeps_body_citations_only():
    links = extract_links(ARTICLE, "https://techcrunch.com/2026/10/02/apple-fda/")
    assert links == {
        "https://developer.apple.com/news?id=p6zjojqw",
        "https://www.theverge.com/tech/1004295",
    }


def _members():
    return [
        make_item("tc", NOW, url="https://techcrunch.com/apple", source_id="tc"),
        make_item("ars", NOW, url="https://arstechnica.com/apple", source_id="ars"),
        make_item("hn", NOW, url="https://developer.apple.com/news/?id=1", source_id="hn"),
    ]


def _story(ids=("tc", "ars", "hn")):
    return TopStory(id=ids[0], title="Apple", item_ids=list(ids))


def test_member_cited_by_others_becomes_lead():
    links = {
        "tc": {"https://developer.apple.com/news?id=1"},
        "ars": {"https://developer.apple.com/news?id=1", "https://techcrunch.com/apple"},
    }
    story = choose_primary(_story(), _members(), links)
    assert story.item_ids == ["hn", "tc", "ars"]
    assert story.id == "hn"
    assert story.primary_url is None


def test_outside_url_cited_by_two_members_becomes_primary_url():
    advisory = "https://about.gitlab.com/releases/2026/10/01/critical-patch"
    links = {"tc": {advisory, "https://one.example/a"}, "ars": {advisory}}
    story = choose_primary(_story(), _members(), links)
    assert story.primary_url == advisory
    assert story.item_ids == ["tc", "ars", "hn"]


def test_single_citation_or_no_links_changes_nothing():
    story = _story()
    assert choose_primary(story, _members(), {"tc": {"https://one.example/a"}}) is story
    assert choose_primary(story, _members(), {}) is story


class FakeResponse:
    def __init__(self, text="", status=200, content_type="text/html"):
        self.text = text
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.encoding = "utf-8"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size):
        yield self.text.encode()


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        page = self.pages.get(url)
        if isinstance(page, Exception):
            raise page
        return page if page is not None else FakeResponse(status=404)


def test_find_primary_sources_end_to_end():
    members = _members()
    cite_apple = '<p><a href="https://developer.apple.com/news/?id=1">Apple</a></p>'
    session = FakeSession({
        "https://techcrunch.com/apple": FakeResponse(cite_apple),
        "https://arstechnica.com/apple": FakeResponse(cite_apple),
        "https://developer.apple.com/news/?id=1": requests.ConnectionError("down"),
        "https://developer.apple.com/robots.txt": FakeResponse("User-agent: *\nAllow: /"),
    })
    standout = TopStory(id="tc", title="Solo", item_ids=["tc"])

    [story, solo] = find_primary_sources([_story(), standout], members, session)

    assert story.item_ids[0] == "hn"
    assert solo is standout


def test_robots_txt_is_respected_and_pdfs_skipped():
    session = FakeSession({
        "https://blocked.example/robots.txt": FakeResponse("User-agent: *\nDisallow: /"),
        "https://open.example/doc.pdf": FakeResponse("%PDF", content_type="application/pdf"),
    })
    robots = primary._Robots(session)
    assert primary.fetch_page("https://blocked.example/a", session, robots) is None
    assert "https://blocked.example/a" not in session.urls
    assert primary.fetch_page("https://open.example/doc.pdf", session, robots) is None


def test_page_budget_is_capped(monkeypatch):
    monkeypatch.setattr(primary, "MAX_PAGES", 2)
    session = FakeSession({})
    find_primary_sources([_story()], _members(), session)
    assert len([u for u in session.urls if not u.endswith("/robots.txt")]) == 2
