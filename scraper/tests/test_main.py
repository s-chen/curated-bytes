import json

import pytest

import scraper.__main__ as cli
from scraper.models import NewsFeed

from conftest import make_item


@pytest.fixture(autouse=True)
def _no_env_overrides(monkeypatch):
    for var in ("NEWS_SOURCES", "NEWS_OUTPUT", "GITHUB_ACTIONS"):
        monkeypatch.delenv(var, raising=False)


def _sources(path, *ids):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"sources": [{"id": i, "name": i, "url": f"https://{i}.example/feed"} for i in ids]})
    )
    return path


def _fake_fetch(items=None, failed=()):
    def fake(srcs, fetched_at):
        out = items if items is not None else [make_item("a", fetched_at, fetched_at=fetched_at)]
        return out, list(failed)

    return fake


def test_end_to_end_writes_news_json(tmp_path, monkeypatch):
    sources = _sources(tmp_path / "sources.json", "one", "two")
    output = tmp_path / "news.json"
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch(failed=["two"]))

    assert cli.main(["--sources", str(sources), "--output", str(output)]) == cli.EXIT_OK
    feed = NewsFeed.model_validate_json(output.read_text())
    assert [i.id for i in feed.items] == ["a"]


def test_defaults_are_relative_to_working_directory(tmp_path, monkeypatch):
    """Running from scraper/ uses config/ and ../web-dashboard/public, wherever the package lives."""
    scraper_dir = tmp_path / "repo" / "scraper"
    _sources(scraper_dir / "config" / "news_sources.json", "one")
    public = tmp_path / "repo" / "web-dashboard" / "public"
    public.mkdir(parents=True)
    monkeypatch.chdir(scraper_dir)
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch())

    assert cli.main([]) == cli.EXIT_OK
    assert (public / "news.json").exists()


def test_missing_sources_file_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == cli.EXIT_FAILED


def test_missing_output_directory_fails_without_creating_it(tmp_path, monkeypatch):
    sources = _sources(tmp_path / "sources.json", "one")
    output = tmp_path / "nope" / "news.json"
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch())

    assert cli.main(["--sources", str(sources), "--output", str(output)]) == cli.EXIT_FAILED
    assert not output.parent.exists()


def test_all_sources_failing_exits_nonzero_and_keeps_output(tmp_path, monkeypatch):
    sources = _sources(tmp_path / "sources.json", "one")
    output = tmp_path / "news.json"
    output.write_text('{"generated_at": "2026-10-03T00:00:00Z", "items": []}')
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch(items=[], failed=["one"]))

    assert cli.main(["--sources", str(sources), "--output", str(output)]) == cli.EXIT_FAILED
    assert output.read_text() == '{"generated_at": "2026-10-03T00:00:00Z", "items": []}'


def test_corrupt_existing_output_is_not_overwritten(tmp_path, monkeypatch):
    sources = _sources(tmp_path / "sources.json", "one")
    output = tmp_path / "news.json"
    output.write_text("{corrupt")
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch())

    assert cli.main(["--sources", str(sources), "--output", str(output)]) == cli.EXIT_FAILED
    assert output.read_text() == "{corrupt"


def test_too_many_failures_writes_but_exits_degraded(tmp_path, monkeypatch):
    sources = _sources(tmp_path / "sources.json", "one", "two", "three")
    output = tmp_path / "news.json"
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch(failed=["two", "three"]))

    assert cli.main(["--sources", str(sources), "--output", str(output)]) == cli.EXIT_DEGRADED
    assert output.exists()


def test_failed_feeds_annotated_on_github_actions(tmp_path, monkeypatch, capsys):
    sources = _sources(tmp_path / "sources.json", "one", "two")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch(failed=["two"]))

    cli.main(["--sources", str(sources), "--output", str(tmp_path / "news.json")])

    assert "::warning title=Feed failed::Source 'two'" in capsys.readouterr().out
