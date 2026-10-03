"""CLI entry point: `python -m scraper`, run from the `scraper/` directory.

Default paths are relative to the current directory, so they work the same whether or not
the package is pip-installed. Override with flags or env vars (as the Docker image does).
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError

from scraper.fetch import fetch_all
from scraper.sources import load_sources
from scraper.store import StoreError, load_existing, merge, write_feed

DEFAULT_SOURCES = Path("config/news_sources.json")
DEFAULT_OUTPUT = Path("../web-dashboard/public/news.json")

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
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def _annotate_failures(failed: list[str]) -> None:
    """Surface failed feeds as GitHub Actions warnings, so a dead feed is visible in the run."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for source_id in failed:
        print(f"::warning title=Feed failed::Source '{source_id}' could not be fetched")


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

    now = datetime.now(timezone.utc)
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
    try:
        write_feed(args.output, items, generated_at=now)
    except (OSError, StoreError) as exc:
        log.error("Can't write %s: %s", args.output.resolve(), exc)
        return EXIT_FAILED

    new_count = len({i.id for i in items} - {i.id for i in existing})
    log.info(
        "Wrote %d items (%d new) to %s; %d/%d sources failed%s",
        len(items), new_count, args.output, len(failed), len(sources),
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
