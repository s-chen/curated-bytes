"""Primary sources for top stories, found by following the links in their articles.

For each multi-source top story, fetch the member articles and collect the links in their
body text (navigation, headers, footers and asides are skipped, as are links within the same
site and to social media). Then:

- If an article links to another member's URL (e.g. TechCrunch linking to Apple's own post,
  which Hacker News also carried), that member is the primary source and becomes the lead.
- Otherwise, a URL that at least `MIN_CITERS` members link to (an advisory, a release, a
  filing) is recorded as the story's `primary_url`.

Bounded and polite: at most `MAX_PAGES` pages per run, each capped in size and time, and
robots.txt is respected. Any failure leaves a story exactly as it was.
"""

import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests

from scraper.dedupe import normalise_url
from scraper.fetch import USER_AGENT
from scraper.models import NewsItem, TopStory

log = logging.getLogger(__name__)

MAX_PAGES = 40  # per run, across all top stories
MAX_PAGE_BYTES = 2 * 1024 * 1024
PAGE_TIMEOUT_SECONDS = 10
PAGE_DEADLINE_SECONDS = 20
MIN_CITERS = 2  # members that must link to an outside URL for it to count as primary
MAX_WORKERS = 8

# Links that are never a primary source: social media, video, shops, search, encyclopedias.
SKIP_SITES = {
    "twitter.com", "x.com", "t.co", "facebook.com", "instagram.com", "linkedin.com",
    "reddit.com", "threads.net", "bsky.app", "mastodon.social", "youtube.com", "youtu.be",
    "tiktok.com", "amazon.com", "google.com", "apple.news", "wikipedia.org", "archive.org",
    "flipboard.com", "pinterest.com",
}
# Page regions whose links are site chrome, not citations.
SKIP_CONTAINERS = {"nav", "header", "footer", "aside", "form"}
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu"}


def site_key(host: str) -> str:
    """Registrable-ish domain: news.example.co.uk -> example.co.uk, a.b.example.com -> example.com."""
    labels = host.lower().removeprefix("www.").split(".")
    if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in SKIP_CONTAINERS:
            self._skip_depth += 1
        elif tag == "a" and not self._skip_depth:
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_CONTAINERS and self._skip_depth:
            self._skip_depth -= 1


def extract_links(html: str, page_url: str) -> set[str]:
    """Normalised outbound links from an article's body that could be a primary source."""
    parser = _LinkExtractor()
    parser.feed(html)
    parser.close()
    own_site = site_key(urlsplit(page_url).hostname or "")
    links = set()
    for href in parser.hrefs:
        url = urljoin(page_url, href.strip())
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme not in ("http", "https") or not host:
            continue
        site = site_key(host)
        if site == own_site or site in SKIP_SITES or parts.path in ("", "/"):
            continue
        links.add(normalise_url(url))
    return links


class _Robots:
    """robots.txt per host, fetched once per run. Unreachable or 5xx: don't fetch the host."""

    def __init__(self, session: requests.Session) -> None:
        self.session = session
        self.cache: dict[str, RobotFileParser | bool] = {}

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.cache:
            parser: RobotFileParser | bool
            try:
                response = self.session.get(
                    f"{origin}/robots.txt", headers={"User-Agent": USER_AGENT},
                    timeout=PAGE_TIMEOUT_SECONDS,
                )
                if response.status_code >= 500:
                    parser = False
                elif response.status_code >= 400:
                    parser = True  # no robots.txt: everything allowed
                else:
                    parser = RobotFileParser()
                    parser.parse(response.text.splitlines())
            except requests.RequestException:
                parser = False
            self.cache[origin] = parser
        rules = self.cache[origin]
        if isinstance(rules, bool):
            return rules
        return rules.can_fetch(USER_AGENT, url)


def fetch_page(url: str, session: requests.Session, robots: _Robots) -> str | None:
    """An article's HTML, or None if disallowed, too big, too slow or not HTML."""
    page = fetch_html(url, session, robots)
    return page[0] if page else None


def fetch_html(url: str, session: requests.Session, robots: _Robots) -> tuple[str, str] | None:
    """(HTML, final URL after redirects), or None if disallowed, too big, too slow or not HTML."""
    if not robots.allowed(url):
        log.debug("robots.txt disallows %s", url)
        return None
    deadline = time.monotonic() + PAGE_DEADLINE_SECONDS
    try:
        with session.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=PAGE_TIMEOUT_SECONDS, stream=True
        ) as response:
            response.raise_for_status()
            if "html" not in response.headers.get("Content-Type", "html"):
                return None
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                body += chunk
                if len(body) > MAX_PAGE_BYTES or time.monotonic() > deadline:
                    return None
            html = bytes(body).decode(response.encoding or "utf-8", errors="replace")
            return html, getattr(response, "url", None) or url
    except requests.RequestException as exc:
        log.debug("Can't fetch %s: %s", url, exc)
        return None


def choose_primary(
    story: TopStory, members: list[NewsItem], links: dict[str, set[str]]
) -> TopStory:
    """Reorder or annotate one story from its members' links ({item id: links})."""
    member_urls = {normalise_url(m.url): m for m in members}

    # A member cited by another member is the primary source.
    cited = Counter(
        member_urls[url].id
        for m in members
        for url in links.get(m.id, set())
        if url in member_urls and member_urls[url].id != m.id
    )
    if cited:
        top = max(cited.values())
        lead = next(m for m in members if cited.get(m.id) == top)  # ties: Gemini's order
        if lead.id != story.item_ids[0]:
            order = [lead.id] + [i for i in story.item_ids if i != lead.id]
            return story.model_copy(update={"id": lead.id, "item_ids": order})
        return story

    # Otherwise an outside URL several members cite.
    outside = Counter(
        url for m in members for url in links.get(m.id, set()) if url not in member_urls
    )
    best = [url for url, n in outside.most_common() if n >= MIN_CITERS]
    if best:
        return story.model_copy(update={"primary_url": best[0]})
    return story


def find_primary_sources(
    top_stories: list[TopStory], items: list[NewsItem], session: requests.Session | None = None
) -> tuple[list[TopStory], dict[str, set[str]]]:
    """Primary sources for multi-source top stories. Single-source standouts are unchanged.

    Also returns the links found in each article ({item id: links}), for site discovery.
    """
    if session is None:
        with requests.Session() as own_session:
            return find_primary_sources(top_stories, items, own_session)

    by_id = {i.id: i for i in items}
    to_fetch: dict[str, str] = {}  # item id -> url, in story rank order, capped
    for story in top_stories:
        if len(story.item_ids) < 2:
            continue
        for item_id in story.item_ids:
            item = by_id.get(item_id)
            if item and item_id not in to_fetch and len(to_fetch) < MAX_PAGES:
                if site_key(urlsplit(item.url).hostname or "") not in SKIP_SITES:
                    to_fetch[item_id] = item.url

    robots = _Robots(session)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        pages = dict(zip(to_fetch, pool.map(lambda u: fetch_page(u, session, robots), to_fetch.values())))
    links = {
        item_id: extract_links(html, to_fetch[item_id]) for item_id, html in pages.items() if html
    }
    log.info("Followed links in %d/%d top-story articles", len(links), len(to_fetch))

    out = []
    for story in top_stories:
        members = [by_id[i] for i in story.item_ids if i in by_id]
        updated = choose_primary(story, members, links) if len(members) >= 2 else story
        if updated is not story:
            log.info(
                "Primary source for %r: %s",
                story.title,
                updated.primary_url or by_id[updated.item_ids[0]].url,
            )
        out.append(updated)
    return out, links
