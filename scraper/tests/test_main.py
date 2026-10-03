import json

import scraper.__main__ as cli
from scraper.models import NewsFeed

from conftest import make_item


def _sources(tmp_path, *ids):
    path = tmp_path / "sources.json"
    path.write_text(
        json.dumps({"sources": [{"id": i, "name": i, "url": f"https://{i}.example/feed"} for i in ids]})
    )
    return path


def test_end_to_end_writes_news_json(tmp_path, monkeypatch):
    sources = _sources(tmp_path, "one", "two")
    output = tmp_path / "news.json"

    def fake_fetch_all(srcs, fetched_at):
        return [make_item("a", fetched_at, fetched_at=fetched_at)], ["two"]

    monkeypatch.setattr(cli, "fetch_all", fake_fetch_all)

    assert cli.main(["--sources", str(sources), "--output", str(output)]) == 0
    feed = NewsFeed.model_validate_json(output.read_text())
    assert [i.id for i in feed.items] == ["a"]


def test_all_sources_failing_exits_nonzero_and_keeps_output(tmp_path, monkeypatch):
    sources = _sources(tmp_path, "one")
    output = tmp_path / "news.json"
    output.write_text("previous")

    monkeypatch.setattr(cli, "fetch_all", lambda srcs, fetched_at: ([], ["one"]))

    assert cli.main(["--sources", str(sources), "--output", str(output)]) == 1
    assert output.read_text() == "previous"
