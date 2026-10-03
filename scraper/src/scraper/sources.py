"""Loads and validates the news source list."""

from pathlib import Path

from scraper.models import Source, SourcesConfig


def load_sources(path: Path) -> list[Source]:
    """Return the enabled sources from a JSON config file.

    Raises `ValueError` if source ids are not unique.
    """
    config = SourcesConfig.model_validate_json(path.read_text(encoding="utf-8"))

    ids = [s.id for s in config.sources]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"Duplicate source ids in {path}: {', '.join(duplicates)}")

    return [s for s in config.sources if s.enabled]
