import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scraper.sources import load_sources

REPO_SOURCES = Path(__file__).parents[1] / "config" / "news_sources.json"


def _write(tmp_path: Path, sources: list[dict]) -> Path:
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"sources": sources}))
    return path


def test_repo_sources_file_is_valid():
    sources = load_sources(REPO_SOURCES)
    assert sources, "news_sources.json should have at least one enabled source"
    assert all(s.category == "tech" for s in sources)
    assert {s.weight for s in sources} > {1}, "major outlets should outweigh small sites"


def test_weight_defaults_to_one(tmp_path):
    path = _write(tmp_path, [{"id": "a", "name": "A", "url": "https://a.example/feed"}])
    assert load_sources(path)[0].weight == 1


def test_disabled_sources_are_skipped(tmp_path):
    path = _write(
        tmp_path,
        [
            {"id": "a", "name": "A", "url": "https://a.example/feed"},
            {"id": "b", "name": "B", "url": "https://b.example/feed", "enabled": False},
        ],
    )
    assert [s.id for s in load_sources(path)] == ["a"]


def test_duplicate_ids_rejected(tmp_path):
    path = _write(
        tmp_path,
        [
            {"id": "a", "name": "A", "url": "https://a.example/feed"},
            {"id": "a", "name": "A2", "url": "https://a2.example/feed"},
        ],
    )
    with pytest.raises(ValueError, match="Duplicate source ids"):
        load_sources(path)


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "a", "name": "A", "url": "not-a-url"},
        {"id": "Bad Id", "name": "A", "url": "https://a.example/feed"},
        {"name": "A", "url": "https://a.example/feed"},
        {"id": "a", "name": "A", "url": "https://a.example/feed", "weight": 0},
        {"id": "a", "name": "A", "url": "https://a.example/feed", "weight": 4},
    ],
)
def test_invalid_source_rejected(tmp_path, bad):
    with pytest.raises(ValidationError):
        load_sources(_write(tmp_path, [bad]))
