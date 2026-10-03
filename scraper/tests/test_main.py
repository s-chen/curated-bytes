import json
from datetime import timedelta

import pytest

import scraper.__main__ as cli
from scraper.dedupe import item_id
from scraper.models import NewsFeed, TopStory
from scraper.store import write_feed
from scraper.editor import EditorError, EditorResult

from conftest import NOW, make_item


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr(cli, "_now", lambda: NOW)


@pytest.fixture(autouse=True)
def _no_link_following(monkeypatch):
    monkeypatch.setattr(cli, "find_primary_sources", lambda stories, items: (stories, {}))


@pytest.fixture(autouse=True)
def _site_stats_in_tmp(monkeypatch, tmp_path, _no_env_overrides):
    monkeypatch.setenv("SITE_STATS", str(tmp_path / "state" / "site_stats.json"))


@pytest.fixture(autouse=True)
def _no_env_overrides(monkeypatch):
    for var in (
        "NEWS_SOURCES", "NEWS_OUTPUT", "GITHUB_ACTIONS",
        "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_FALLBACK_MODEL", "GEMINI_DEBUG_DIR", "SITE_STATS",
    ):
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

    def fake_editor(items, now, api_key, weights, model, **kwargs):
        calls.append(([i.id for i in items if i.review == "pending"], api_key, weights, model))
        return EditorResult(
            reviewed={"news", "gemini-says-no"},
            excluded={"gemini-says-no": "self-promotion"},
            top_stories=[TopStory(id="news", title="Big", item_ids=["news"])],
            model="custom-model",
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


def test_primary_source_failure_keeps_top_stories(tmp_path, monkeypatch):
    sources = _sources(tmp_path / "sources.json", "one")
    output = tmp_path / "news.json"
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch(items=[make_item("a", NOW), make_item("b", NOW)]))
    story = TopStory(id="a", title="Big", item_ids=["a", "b"])
    monkeypatch.setattr(cli, "run_editor", lambda *a, **k: EditorResult(reviewed={"a", "b"}, top_stories=[story]))

    def boom(stories, items):
        raise RuntimeError("network on fire")

    monkeypatch.setattr(cli, "find_primary_sources", boom)
    assert _run(sources, output) == cli.EXIT_OK
    assert [s.title for s in NewsFeed.model_validate_json(output.read_text()).top_stories] == ["Big"]


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


def test_kept_items_can_be_excluded_later_but_never_come_back(tmp_path, monkeypatch):
    sources = _sources(tmp_path / "sources.json", "one")
    output = tmp_path / "news.json"
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    item = make_item(item_id("https://example.com/a"), NOW, url="https://example.com/a")
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch(items=[item]))

    def review_with(**result):
        monkeypatch.setattr(
            cli, "run_editor",
            lambda *a, **k: EditorResult(reviewed={item.id}, model=cli.DEFAULT_MODEL, **result),
        )
        _run(sources, output)
        [stored] = NewsFeed.model_validate_json(output.read_text()).items
        return stored.review

    assert review_with() == "kept"
    assert review_with(excluded={item.id: "off topic"}) == "excluded"  # e.g. after a prompt change
    assert review_with() == "excluded"  # never flips back

def test_engineering_flag_follows_the_sources_config(tmp_path, monkeypatch):
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps({"sources": [
        {"id": "eng", "name": "Eng", "url": "https://eng.example/feed", "engineering": True},
        {"id": "news", "name": "News", "url": "https://news.example/feed"},
    ]}))
    output = tmp_path / "news.json"
    items = [make_item("e", NOW, source_id="eng"), make_item("n", NOW, source_id="news")]
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch(items=items))

    assert _run(sources, output) == cli.EXIT_OK
    feed = NewsFeed.model_validate_json(output.read_text())
    assert {i.source_id: i.engineering for i in feed.items} == {"eng": True, "news": False}


def test_runs_record_site_citations_and_sites_flag_reports_them(tmp_path, monkeypatch, capsys):
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps({"sources": [
        {"id": "hn", "name": "Hacker News", "url": "https://hnrss.org/frontpage", "aggregator": True},
    ]}))
    output = tmp_path / "news.json"
    items = [make_item(f"hn{n}", NOW, url=f"https://lwn.net/{n}", source_id="hn") for n in range(3)]
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch(items=items))
    assert _run(sources, output) == cli.EXIT_OK
    assert (tmp_path / "state" / "site_stats.json").exists()

    monkeypatch.setattr(cli, "fetch_all", lambda *a, **k: pytest.fail("fetched"))
    args = ["--sources", str(sources), "--output", str(output), "--sites", "--find-feeds", "0"]
    assert cli.main(args) == cli.EXIT_OK
    assert "lwn.net: 3 citations from Hacker News" in capsys.readouterr().out

def test_top_stories_survive_a_later_gemini_failure(tmp_path, monkeypatch):
    sources = _sources(tmp_path / "sources.json", "one")
    output = tmp_path / "news.json"
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    a = make_item(item_id("https://example.com/a"), NOW, url="https://example.com/a", source_id="x")
    b = make_item(item_id("https://example.com/b"), NOW, url="https://example.com/b", source_id="y")
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch(items=[a, b]))
    story = TopStory(id=a.id, title="Big", item_ids=[a.id, b.id])
    monkeypatch.setattr(cli, "run_editor", lambda *x, **k: EditorResult(reviewed={a.id, b.id}, top_stories=[story]))
    _run(sources, output)

    def boom(*args, **kwargs):
        raise EditorError("Gemini request failed: 503")

    monkeypatch.setattr(cli, "run_editor", boom)
    monkeypatch.setattr(cli, "_now", lambda: NOW + timedelta(hours=1))
    _run(sources, output)

    [kept] = NewsFeed.model_validate_json(output.read_text()).top_stories
    assert (kept.title, kept.first_shown, kept.last_shown) == ("Big", NOW, NOW + timedelta(hours=1))


@pytest.mark.parametrize(
    "env, expected",
    [
        (None, ["gemini-3.7-flash", "gemini-3.5-flash-lite"]),
        ("a, b ,", ["a", "b"]),
        ("", []),
    ],
)
def test_fallback_models_from_env(monkeypatch, env, expected):
    if env is not None:
        monkeypatch.setenv("GEMINI_FALLBACK_MODEL", env)
    assert cli._fallback_models() == expected


def test_only_the_main_model_can_exclude(tmp_path, monkeypatch):
    sources = _sources(tmp_path / "sources.json", "one")
    output = tmp_path / "news.json"
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_MODEL", "main")
    a = make_item(item_id("https://example.com/a"), NOW, url="https://example.com/a")
    monkeypatch.setattr(cli, "fetch_all", _fake_fetch(items=[a]))

    def review_by(model):
        result = EditorResult(reviewed={a.id}, excluded={a.id: "harsh"}, model=model)
        monkeypatch.setattr(cli, "run_editor", lambda *x, **k: result)
        _run(sources, output)
        [stored] = NewsFeed.model_validate_json(output.read_text()).items
        return stored.review

    assert review_by("lite") == "pending"  # a fallback can't exclude
    assert review_by("main") == "excluded"
