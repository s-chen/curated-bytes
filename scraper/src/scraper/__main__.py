"""CLI entry point: `python -m scraper`."""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scraper.fetch import fetch_all
from scraper.sources import load_sources
from scraper.store import load_existing, merge, write_feed

_SCRAPER_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCES = _SCRAPER_ROOT / "config" / "news_sources.json"
DEFAULT_OUTPUT = _SCRAPER_ROOT.parent / "web-dashboard" / "public" / "news.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch tech news feeds into news.json.")
    parser.add_argument(
        "--sources",
        type=Path,
        default=Path(os.environ.get("NEWS_SOURCES", DEFAULT_SOURCES)),
        help="news sources JSON (env: NEWS_SOURCES)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.environ.get("NEWS_OUTPUT", DEFAULT_OUTPUT)),
        help="news.json to merge into and write (env: NEWS_OUTPUT)",
    )
    parser.add_argument("--max-age-days", type=int, default=7)
    parser.add_argument("--max-items", type=int, default=500)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("scraper")

    sources = load_sources(args.sources)
    if not sources:
        log.error("No enabled sources in %s", args.sources)
        return 1

    now = datetime.now(timezone.utc)
    fresh, failed = fetch_all(sources, fetched_at=now)
    if len(failed) == len(sources):
        log.error("All %d sources failed; leaving %s untouched", len(sources), args.output)
        return 1

    existing = load_existing(args.output)
    items = merge(
        existing,
        fresh,
        now=now,
        max_age=timedelta(days=args.max_age_days),
        max_items=args.max_items,
    )
    write_feed(args.output, items, generated_at=now)

    new_count = len({i.id for i in items} - {i.id for i in existing})
    log.info(
        "Wrote %d items (%d new) to %s; %d/%d sources failed",
        len(items), new_count, args.output, len(failed), len(sources),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
