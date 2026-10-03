import json

import pytest

import scraper.__main__ as cli
from scraper.dedupe import item_id
from scraper.models import NewsFeed, TopStory
from scraper.store import write_feed
from scraper.editor import EditorError, EditorResult

from conftest import NOW, make_item


@pytest.fixture(autouse=True)
def _no_env_overrides(monkeypatch):
    for var in ("NEWS_SOURCES", "NEWS_OUTPUT", "GITHUB_ACTIONS", "GEMINI_API_KEY", "GEMINI_MODEL"):
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


def _run(sources, output):
    return cli.main(["--sources", str(sources), "--output", str(output)])


def test_without_api_key_new_items_stay_pending(tmp_path, monkeypatch):
    sources = _sources(tmp_path / "sources.json", "one")
    output = tmp_path / "news.json"
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch())
    monkeypatch.setattr(cli, "run_editor", lambda *a, **k: pytest.fail("called Gemini"))

    assert _run(sources, output) == cli.EXIT_OK
    feed = NewsFeed.model_validate_json(output.read_text())
    assert [i.review for i in feed.items] == ["pending"]
    assert feed.top_stories == []


def test_rules_then_gemini_review_and_top_stories(tmp_path, monkeypatch):
    sources = _sources(tmp_path / "sources.json", "one")
    output = tmp_path / "news.json"
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_MODEL", "custom-model")
    items = [
        make_item("news", NOW),
        make_item("promo", NOW, title="Best Prime Day deals"),
        make_item("gemini-says-no", NOW),
    ]
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch(items=items))
    calls = []

    def fake_editor(items, now, api_key, weights, model):
        calls.append(([i.id for i in items if i.review == "pending"], api_key, weights, model))
        return EditorResult(
            reviewed={"news", "gemini-says-no"},
            excluded={"gemini-says-no": "self-promotion"},
            top_stories=[TopStory(id="news", title="Big", item_ids=["news", "x"])],
        )

    monkeypatch.setattr(cli, "run_editor", fake_editor)

    assert _run(sources, output) == cli.EXIT_OK
    # The rule-matched promo never reaches Gemini.
    assert calls == [(["news", "gemini-says-no"], "k", {"one": 1}, "custom-model")]
    feed = NewsFeed.model_validate_json(output.read_text())
    assert {i.id: i.review for i in feed.items} == {
        "news": "kept",
        "promo": "excluded",
        "gemini-says-no": "excluded",
    }
    assert [s.title for s in feed.top_stories] == ["Big"]


def test_gemini_failure_still_writes_news_with_items_pending(tmp_path, monkeypatch, capsys):
    sources = _sources(tmp_path / "sources.json", "one")
    output = tmp_path / "news.json"
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch())

    def boom(*args, **kwargs):
        raise EditorError("Gemini request failed: 429")

    monkeypatch.setattr(cli, "run_editor", boom)

    assert _run(sources, output) == cli.EXIT_OK
    feed = NewsFeed.model_validate_json(output.read_text())
    assert [(i.id, i.review) for i in feed.items] == [("a", "pending")]
    assert feed.top_stories == []
    assert "::warning title=Gemini review skipped::Gemini request failed: 429" in capsys.readouterr().out


def test_reviewed_items_are_not_reviewed_again(tmp_path, monkeypatch):
    sources = _sources(tmp_path / "sources.json", "one")
    output = tmp_path / "news.json"
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    item = make_item(item_id("https://example.com/a"), NOW, url="https://example.com/a")
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch(items=[item]))
    monkeypatch.setattr(cli, "run_editor", lambda *a, **k: EditorResult(reviewed={item.id}))
    _run(sources, output)

    # Next run: Gemini would now exclude it, but a kept story never flips.
    monkeypatch.setattr(
        cli, "run_editor", lambda *a, **k: EditorResult(reviewed={item.id}, excluded={item.id: "x"})
    )
    _run(sources, output)
    [stored] = NewsFeed.model_validate_json(output.read_text()).items
    assert stored.review == "kept"


def test_sites_flag_prints_report_without_fetching(tmp_path, monkeypatch, capsys):
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps({"sources": [
        {"id": "hn", "name": "Hacker News", "url": "https://hnrss.org/frontpage", "aggregator": True},
    ]}))
    output = tmp_path / "news.json"
    write_feed(output, [make_item(f"hn{n}", NOW, url=f"https://lwn.net/{n}", source_id="hn") for n in range(3)], generated_at=NOW)
    monkeypatch.setattr(cli, "fetch_all", lambda *a, **k: pytest.fail("fetched"))

    assert cli.main(["--sources", str(sources), "--output", str(output), "--sites"]) == cli.EXIT_OK
    assert "lwn.net  3 links" in capsys.readouterr().out
