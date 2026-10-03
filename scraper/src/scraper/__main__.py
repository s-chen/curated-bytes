"""CLI entry point: `python -m scraper`, run from the `scraper/` directory.

Default paths are relative to the current directory, so they work the same whether or not
the package is pip-installed. Override with flags or env vars (as the Docker image does).
"""

import argparse
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError

from scraper.editor import (
    DEFAULT_FALLBACK_MODELS,
    DEFAULT_MODEL,
    EditorError,
    apply_review,
    run_editor,
)
from scraper.fetch import fetch_all
from scraper.filters import apply_rules
from scraper.models import NewsItem, Source, TopStory
from scraper.primary import find_primary_sources
from scraper.sites import (
    add_feeds,
    format_report,
    load_stats,
    record_citations,
    save_stats,
    site_report,
)
from scraper.sources import load_sources
from scraper.store import StoreError, load_existing, load_top_stories, merge, write_feed
from scraper.top_stories import settle_top_stories

DEFAULT_SOURCES = Path("config/news_sources.json")
DEFAULT_OUTPUT = Path("../web-dashboard/public/news.json")
DEFAULT_SITE_STATS = Path("state/site_stats.json")

EXIT_OK = 0
EXIT_FAILED = 1  # nothing written
EXIT_DEGRADED = 2  # written, but too many sources failed

log = logging.getLogger("scraper")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch tech news feeds into news.json.")
    parser.add_argument(
        "--sources",
        type=Path,
        default=Path(os.environ.get("NEWS_SOURCES", DEFAULT_SOURCES)),
        help="news sources JSON (env: NEWS_SOURCES; default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.environ.get("NEWS_OUTPUT", DEFAULT_OUTPUT)),
        help="news.json to merge into and write (env: NEWS_OUTPUT; default: %(default)s)",
    )
    parser.add_argument("--max-age-days", type=int, default=7)
    parser.add_argument("--max-items", type=int, default=500)
    parser.add_argument(
        "--max-failed-ratio",
        type=float,
        default=0.5,
        help="exit %d (after writing) if more than this share of sources fail" % EXIT_DEGRADED,
    )
    parser.add_argument(
        "--sites",
        action="store_true",
        help="print the site report (sites aggregators link to that we don't follow) and exit",
    )
    parser.add_argument("--min-links", type=int, default=3, help="for --sites (default: 3)")
    parser.add_argument(
        "--find-feeds",
        type=int,
        default=10,
        help="for --sites: look up feeds for this many top sites, 0 to skip (default: 10)",
    )
    parser.add_argument(
        "--site-stats",
        type=Path,
        default=Path(os.environ.get("SITE_STATS", DEFAULT_SITE_STATS)),
        help="site citation tallies (env: SITE_STATS; default: %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def _now() -> datetime:
    """The run's timestamp (a function so tests can fix the clock)."""
    return datetime.now(timezone.utc)


def _github_warning(title: str, message: str) -> None:
    """Surface a problem as a GitHub Actions warning, so it's visible in the run summary."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning title={title}::{message}")


def _annotate_failures(failed: list[str]) -> None:
    for source_id in failed:
        _github_warning("Feed failed", f"Source '{source_id}' could not be fetched")


def _fallback_models() -> list[str]:
    """GEMINI_FALLBACK_MODEL: comma-separated models to try in order; "" disables fallback."""
    value = os.environ.get("GEMINI_FALLBACK_MODEL")
    if value is None:
        return list(DEFAULT_FALLBACK_MODELS)
    return [m.strip() for m in value.split(",") if m.strip()]


def _review(
    items: list[NewsItem], now: datetime, weights: dict[str, int]
) -> tuple[list[NewsItem], list[TopStory], bool]:
    """Review pending items and pick top stories with Gemini.

    Rule-based exclusions apply first, so Gemini never sees those items. Without an API key,
    or if Gemini fails, the rest stay pending (hidden) until a later run reviews them.
    """
    items, rule_excluded = apply_rules(items)
    by_id = {i.id: i for i in items}
    for item_id, reason in rule_excluded.items():
        log.info("Excluded by rule (%s): %s", reason, by_id[item_id].title)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.warning("GEMINI_API_KEY not set: new stories stay pending and are not shown")
        return items, [], False
    model = os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    try:
        result = run_editor(
            items,
            now,
            api_key,
            weights,
            model=model,
            fallback_models=_fallback_models(),
            debug_dir=Path(d) if (d := os.environ.get("GEMINI_DEBUG_DIR")) else None,
        )
    except EditorError as exc:
        log.warning("Gemini review skipped; new stories stay pending: %s", exc)
        _github_warning("Gemini review skipped", str(exc))
        return items, [], False

    for item_id, reason in result.excluded.items():
        if by_id[item_id].review != "excluded":
            log.info("Excluded by Gemini (%s): %s", reason, by_id[item_id].title)
    log.info(
        "Gemini (%s) reviewed %d items; %d top stories",
        result.model, len(result.reviewed), len(result.top_stories),
    )
    return apply_review(items, result), result.top_stories, True


def _record_sites(
    path: Path, items: list[NewsItem], links: dict[str, set[str]], sources: list[Source], now: datetime
) -> None:
    """Add this run's citations to the site tallies used by `--sites`. Never fails the run."""
    try:
        aggregators = {s.id for s in sources if s.aggregator}
        save_stats(path, record_citations(load_stats(path), items, links, aggregators, now))
    except OSError as exc:
        log.warning("Can't update site stats at %s: %s", path, exc)


def run(args: argparse.Namespace) -> int:
    try:
        sources = load_sources(args.sources)
    except (OSError, ValueError, ValidationError) as exc:
        log.error("Can't load sources from %s: %s", args.sources.resolve(), exc)
        return EXIT_FAILED
    if not sources:
        log.error("No enabled sources in %s", args.sources)
        return EXIT_FAILED

    # Check the output side before fetching, so a bad path or file fails fast and is never
    # overwritten.
    if not args.output.parent.is_dir():
        log.error("Output directory does not exist: %s", args.output.parent.resolve())
        return EXIT_FAILED
    try:
        existing = load_existing(args.output)
    except StoreError as exc:
        log.error("%s. Fix or delete it, then re-run.", exc)
        return EXIT_FAILED

    if args.sites:
        stats = load_stats(args.site_stats)
        report = site_report(stats, existing, sources, args.min_links)
        if args.find_feeds:
            add_feeds(report, args.find_feeds)
        print(format_report(report, stats, args.min_links))
        return EXIT_OK

    now = _now()
    fresh, failed = fetch_all(sources, fetched_at=now)
    _annotate_failures(failed)
    if len(failed) == len(sources):
        log.error("All %d sources failed; leaving %s untouched", len(sources), args.output)
        return EXIT_FAILED

    items = merge(
        existing,
        fresh,
        now=now,
        max_age=timedelta(days=args.max_age_days),
        max_items=args.max_items,
    )
    # Engineering-blog flags follow the config, so changing it applies to stored items too.
    engineering = {s.id for s in sources if s.engineering}
    items = [i.model_copy(update={"engineering": i.source_id in engineering}) for i in items]
    items, top_stories, answered = _review(items, now, weights={s.id: s.weight for s in sources})
    article_links: dict[str, set[str]] = {}
    if top_stories:
        try:
            top_stories, article_links = find_primary_sources(top_stories, items)
        except Exception as exc:  # following links is a bonus: never fail the run over it
            log.warning("Skipping primary sources: %s", exc)
    _record_sites(args.site_stats, items, article_links, sources, now)
    previous_top, previous_past = load_top_stories(args.output)
    top_stories, past_top_stories = settle_top_stories(
        top_stories, previous_top, previous_past, items, now, gemini_answered=answered
    )
    try:
        write_feed(
            args.output, items, generated_at=now,
            top_stories=top_stories, past_top_stories=past_top_stories,
        )
    except (OSError, StoreError) as exc:
        log.error("Can't write %s: %s", args.output.resolve(), exc)
        return EXIT_FAILED

    new_count = len({i.id for i in items} - {i.id for i in existing})
    reviews = Counter(i.review for i in items)
    log.info(
        "Wrote %d items (%d new; %d kept, %d excluded, %d pending) to %s; %d/%d sources failed%s",
        len(items), new_count, reviews["kept"], reviews["excluded"], reviews["pending"],
        args.output, len(failed), len(sources),
        f": {', '.join(failed)}" if failed else "",
    )

    if len(failed) / len(sources) > args.max_failed_ratio:
        log.error("%d/%d sources failed (limit %.0f%%)", len(failed), len(sources), args.max_failed_ratio * 100)
        return EXIT_DEGRADED
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
