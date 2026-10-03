from datetime import timedelta

from scraper.models import TopStory
from scraper.top_stories import PAST_WINDOW, STICKY, settle_top_stories

from conftest import NOW, make_item

H = timedelta(hours=1)


def _items(**importance):
    return [
        make_item(i, NOW - H, source_id=i[0], review="kept", importance=importance.get(i, 3))
        for i in ["a1", "b1", "c1", "d1", "e1", "f1"]
    ]


def _story(*ids, first=None, last=None, title=None):
    return TopStory(id=ids[0], title=title or "+".join(ids), item_ids=list(ids), first_shown=first, last_shown=last)


def _titles(stories):
    return [s.title for s in stories]


def test_fresh_stories_get_first_and_last_shown():
    [story], past = settle_top_stories([_story("a1", "b1")], [], [], _items(), NOW, True)
    assert (story.first_shown, story.last_shown, past) == (NOW, NOW, [])


def test_a_story_keeps_its_first_shown_across_runs_despite_new_headline():
    previous = [_story("a1", "b1", first=NOW - 2 * H, last=NOW - H)]
    fresh = [_story("b1", "a1", title="Reworded")]
    [story], _ = settle_top_stories(fresh, previous, [], _items(), NOW, True)
    assert (story.title, story.first_shown) == ("Reworded", NOW - 2 * H)


def test_recent_cards_stick_but_old_ones_dont():
    previous = [
        _story("c1", "d1", first=NOW - H, last=NOW - H),  # shown 1h ago: sticks
        _story("e1", "f1", first=NOW - STICKY - H, last=NOW - H),  # shown long ago: moves to past
    ]
    top, past = settle_top_stories([_story("a1", "b1")], previous, [], _items(), NOW, True)
    assert _titles(top) == ["a1+b1", "c1+d1"]
    assert _titles(past) == ["e1+f1"]


def test_sticky_cards_compete_on_importance():
    previous = [_story("c1", "d1", first=NOW - H, last=NOW - H)]
    top, _ = settle_top_stories([_story("a1", "b1")], previous, [], _items(c1=5), NOW, True)
    assert _titles(top) == ["c1+d1", "a1+b1"]


def test_more_important_stories_push_sticky_cards_out(monkeypatch):
    monkeypatch.setattr("scraper.top_stories.MAX_STORIES", 1)
    previous = [_story("c1", "d1", first=NOW - H, last=NOW - H)]
    top, past = settle_top_stories([_story("a1", "b1")], previous, [], _items(a1=5), NOW, True)
    assert (_titles(top), _titles(past)) == (["a1+b1"], ["c1+d1"])


def test_cards_survive_a_gemini_failure_while_recent():
    previous = [_story("c1", "d1", first=NOW - 10 * H, last=NOW - H)]
    top, _ = settle_top_stories([], previous, [], _items(), NOW, gemini_answered=False)
    assert _titles(top) == ["c1+d1"]


def test_stale_or_excluded_stories_drop_out():
    items = _items()
    items[2] = items[2].model_copy(update={"published_at": NOW - 30 * H})  # c1
    items[3] = items[3].model_copy(update={"published_at": NOW - 30 * H})  # d1
    items[4] = items[4].model_copy(update={"review": "excluded"})  # e1
    previous = [_story("c1", "d1", first=NOW - H), _story("e1", "f1", first=NOW - H)]
    top, _ = settle_top_stories([], previous, [], items, NOW, gemini_answered=False)
    assert top == []


def test_singles_rank_after_multi_source_stories():
    top, _ = settle_top_stories([_story("a1"), _story("b1", "c1")], [], [], _items(a1=5), NOW, True)
    assert _titles(top) == ["b1+c1", "a1"]


def test_past_keeps_recent_unique_stories_newest_first():
    previous_past = [
        _story("e1", "f1", first=NOW - 20 * H, last=NOW - 10 * H),
        _story("c1", "d1", first=NOW - 30 * H, last=NOW - PAST_WINDOW - H),  # too old
        _story("b1", "x", first=NOW - 5 * H, last=NOW - 4 * H),  # matches a current story
    ]
    previous = [_story("d1", "a1", first=NOW - 9 * H, last=NOW - H, title="dropped")]
    top, past = settle_top_stories([_story("a1", "b1")], previous, previous_past, _items(), NOW, True)
    assert _titles(top) == ["a1+b1"]
    assert _titles(past) == ["e1+f1"]  # "dropped" shares a1 with the current story
