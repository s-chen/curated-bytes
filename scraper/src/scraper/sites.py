"""Site report: which sites aggregators keep linking to that we don't follow yet.

Techmeme grows its source list by following links. This is the manual version: count the
sites behind stories from aggregator sources (Hacker News, Lobsters), drop the ones we
already follow, and list the rest for a person to decide whether to add.
"""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from scraper.filters import CODE_HOSTS
from scraper.models import NewsItem, Source


@dataclass
class SiteStat:
    host: str
    links: int = 0
    aggregators: set[str] = field(default_factory=set)
    points: int = 0
    examples: list[NewsItem] = field(default_factory=list)


def _host(url: str | None) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.") if url else ""


def site_report(
    items: list[NewsItem], sources: list[Source], min_links: int = 3
) -> list[SiteStat]:
    """Sites linked from aggregator stories at least `min_links` times, most linked first.

    Skips sites we already follow (any host our other sources publish on or are fetched
    from), code-hosting sites, and aggregators' own pages (Ask HN and similar).
    """
    aggregator_ids = {s.id for s in sources if s.aggregator}
    followed = {_host(str(s.url)) for s in sources} | {
        _host(i.url) for i in items if i.source_id not in aggregator_ids
    }

    stats: dict[str, SiteStat] = {}
    for item in items:
        if item.source_id not in aggregator_ids:
            continue
        host = _host(item.url)
        if not host or host in followed or host in CODE_HOSTS or host == _host(item.discussion_url):
            continue
        stat = stats.setdefault(host, SiteStat(host))
        stat.links += 1
        stat.aggregators.add(item.source_name)
        stat.points += item.points or 0
        stat.examples.append(item)

    report = [s for s in stats.values() if s.links >= min_links]
    report.sort(key=lambda s: (s.links, len(s.aggregators), s.points), reverse=True)
    for stat in report:
        stat.examples.sort(key=lambda i: i.points or 0, reverse=True)
    return report


def format_report(report: list[SiteStat], items: list[NewsItem], min_links: int) -> str:
    dates = [i.published_at or i.fetched_at for i in items]
    span = (max(dates) - min(dates)).total_seconds() / 86400 if dates else 0
    header = (
        f"Sites linked from aggregators at least {min_links} times that we don't follow "
        f"(from {len(items)} stored stories over {span:.1f} days):"
    )
    if not report:
        return header + "\n  none"
    width = max(len(s.host) for s in report)
    lines = [header, ""]
    for stat in report:
        via = ", ".join(sorted(stat.aggregators))
        points = f", {stat.points} points" if stat.points else ""
        lines.append(f"  {stat.host:<{width}}  {stat.links} links via {via}{points}")
        for example in stat.examples[:2]:
            lines.append(f"  {'':<{width}}    e.g. {example.title[:90]}")
    lines += ["", "Add any worth following to config/news_sources.json (find its RSS/Atom feed)."]
    return "\n".join(lines)
