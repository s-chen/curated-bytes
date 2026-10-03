"""Site discovery: sites our sources keep citing that we don't follow yet.

Techmeme grows its source list by following links one hop from sources it trusts. This is
the same idea with a person deciding:

1. Every run records citations, one hop out: the sites behind aggregator stories (Hacker
   News, Lobsters), and the sites linked from top-story articles (fetched anyway to find
   primary sources).
2. Citations are kept for `STATS_DAYS` in a small state file, each counted once (an article
   fetched every hour doesn't inflate its links).
3. `--sites` lists the most-cited sites we don't follow, finds each one's RSS/Atom feed, and
   prints a ready-to-paste `news_sources.json` entry. Nothing is added automatically.
"""

import hashlib
import io
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import feedparser
import requests
from pydantic import BaseModel, ValidationError

from scraper.fetch import FeedError, _download
from scraper.filters import CODE_HOSTS
from scraper.models import NewsItem, Source, UtcDatetime
from scraper.primary import SKIP_SITES, _Robots, fetch_html, site_key

log = logging.getLogger(__name__)

STATS_DAYS = 7
COMMON_FEED_PATHS = ["/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml", "/index.xml", "/feed/"]


class Citation(BaseModel):
    source_id: str  # the source whose story cites the site
    item_id: str  # that story
    day: date  # first seen


class SiteStats(BaseModel):
    updated_at: UtcDatetime | None = None
    # host -> {citation key -> citation}; a key is one story linking to one URL.
    sites: dict[str, dict[str, Citation]] = {}


def _host(url: str | None) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.") if url else ""


# --- recording citations ---


def load_stats(path: Path) -> SiteStats:
    """Previous citations. A missing or unreadable file starts afresh: it's only a tally."""
    try:
        return SiteStats.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return SiteStats()
    except (OSError, ValueError, ValidationError) as exc:
        log.warning("Can't read %s, starting site stats afresh: %s", path, exc)
        return SiteStats()


def save_stats(path: Path, stats: SiteStats) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as tmp:
        tmp.write(stats.model_dump_json(indent=1))
    os.chmod(tmp.name, 0o644)
    os.replace(tmp.name, path)


def record_citations(
    stats: SiteStats,
    items: list[NewsItem],
    article_links: dict[str, set[str]],
    aggregator_ids: set[str],
    now: datetime,
) -> SiteStats:
    """Add this run's citations and drop those older than `STATS_DAYS`.

    `article_links` maps a story's id to the links in its article (from the primary-source
    step). Aggregator stories cite the site they link to.
    """
    by_id = {i.id: i for i in items}
    today = now.date()
    sites = {host: dict(cites) for host, cites in stats.sites.items()}

    def add(host: str, key: str, item: NewsItem) -> None:
        if host:
            sites.setdefault(host, {}).setdefault(
                key, Citation(source_id=item.source_id, item_id=item.id, day=today)
            )

    for item in items:
        if item.source_id in aggregator_ids and _host(item.url) != _host(item.discussion_url):
            add(_host(item.url), item.id, item)
    for item_id, urls in article_links.items():
        if item_id in by_id:
            for url in urls:
                digest = hashlib.md5(url.encode()).hexdigest()[:10]
                add(_host(url), f"{item_id}:{digest}", by_id[item_id])

    cutoff = today - timedelta(days=STATS_DAYS)
    sites = {
        host: kept
        for host, cites in sites.items()
        if (kept := {k: c for k, c in cites.items() if c.day > cutoff})
    }
    return SiteStats(updated_at=now, sites=sites)


# --- the report ---


@dataclass
class SiteStat:
    host: str
    links: int = 0
    citing_sources: set[str] = field(default_factory=set)
    last_seen: date | None = None
    examples: list[str] = field(default_factory=list)  # titles of stories citing the site
    feed_checked: bool = False
    feed_url: str | None = None
    feed_title: str | None = None


def site_report(
    stats: SiteStats, items: list[NewsItem], sources: list[Source], min_links: int = 3
) -> list[SiteStat]:
    """Cited sites we don't follow, with at least `min_links` citations, most cited first.

    Skips any site a configured source publishes on or is fetched from, code-hosting sites,
    and social media, shops and the like.
    """
    names = {s.id: s.name for s in sources}
    aggregator_ids = {s.id for s in sources if s.aggregator}
    followed = {site_key(_host(str(s.url))) for s in sources} | {
        site_key(_host(i.url)) for i in items if i.source_id not in aggregator_ids
    }
    titles = {i.id: i.title for i in items}

    report = []
    for host, cites in stats.sites.items():
        site = site_key(host)
        if site in followed or site in SKIP_SITES or host in CODE_HOSTS or len(cites) < min_links:
            continue
        stat = SiteStat(
            host=host,
            links=len(cites),
            citing_sources={names.get(c.source_id, c.source_id) for c in cites.values()},
            last_seen=max(c.day for c in cites.values()),
        )
        stat.examples = list(dict.fromkeys(titles[c.item_id] for c in cites.values() if c.item_id in titles))
        report.append(stat)
    report.sort(key=lambda s: (len(s.citing_sources), s.links), reverse=True)
    return report


# --- finding feeds ---


class _FeedLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = dict(attrs)
        if (
            tag == "link"
            and "alternate" in (a.get("rel") or "").lower().split()
            and re.search(r"(rss|atom)\+xml", a.get("type") or "")
            and a.get("href")
        ):
            self.hrefs.append(a["href"])


def _usable_feed(url: str, session: requests.Session) -> tuple[str, str | None] | None:
    """(feed URL, feed title) if `url` is a feed with entries."""
    try:
        content, final_url = _download(url, session)
    except (requests.RequestException, FeedError):
        return None
    feed = feedparser.parse(io.BytesIO(content))
    if not feed.entries:
        return None
    return final_url, feed.feed.get("title")


def find_feed(host: str, session: requests.Session, robots: _Robots) -> tuple[str, str | None] | None:
    """A site's RSS/Atom feed: the one its homepage advertises, else a common feed path."""
    home = f"https://{host}/"
    candidates = []
    page = fetch_html(home, session, robots)
    if page:
        html, home = page  # resolve against where the homepage redirected (e.g. www.)
        parser = _FeedLinks()
        parser.feed(html)
        candidates += [urljoin(home, href) for href in parser.hrefs]
    candidates += [urljoin(home, path) for path in COMMON_FEED_PATHS]
    for url in dict.fromkeys(candidates):
        if robots.allowed(url) and (found := _usable_feed(url, session)):
            return found
    return None


def add_feeds(report: list[SiteStat], limit: int, session: requests.Session | None = None) -> None:
    """Look up feeds for the first `limit` sites in the report."""
    if session is None:
        with requests.Session() as own_session:
            return add_feeds(report, limit, own_session)
    robots = _Robots(session)
    for stat in report[:limit]:
        stat.feed_checked = True
        if found := find_feed(stat.host, session, robots):
            stat.feed_url, stat.feed_title = found


def source_entry(stat: SiteStat) -> str:
    """A `news_sources.json` entry to paste. Weight 1 (small site) until you decide otherwise."""
    entry = {
        "id": re.sub(r"[^a-z0-9]+", "-", stat.host).strip("-"),
        "name": (stat.feed_title or stat.host).strip()[:60],
        "url": stat.feed_url,
        "category": "tech",
        "weight": 1,
    }
    return json.dumps(entry, ensure_ascii=False)


def format_report(report: list[SiteStat], stats: SiteStats, min_links: int) -> str:
    total = sum(len(c) for c in stats.sites.values())
    header = (
        f"Sites our sources cited at least {min_links} times in the last {STATS_DAYS} days "
        f"that we don't follow ({total} citations recorded):"
    )
    if not report:
        return header + "\n  none yet: citations build up with each hourly run"
    lines = [header]
    for stat in report:
        via = ", ".join(sorted(stat.citing_sources))
        lines += ["", f"  {stat.host}: {stat.links} citations from {via} (last {stat.last_seen})"]
        lines += [f"    e.g. {title[:90]}" for title in stat.examples[:2]]
        if stat.feed_url:
            lines.append(f"    feed: {source_entry(stat)},")
        elif stat.feed_checked:
            lines.append("    feed: none found")
    lines += ["", "Paste the feeds worth following into config/news_sources.json and set their weight."]
    return "\n".join(lines)
