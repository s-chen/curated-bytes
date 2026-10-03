"""How long top stories stay: a rolling day, a little stickiness, and an "earlier" list.

Gemini picks top stories afresh each run, and its picks vary. Like Techmeme's rolling front
page, a story stays a top story while it has coverage from the last day (`is_recent`), and:

- A card shown recently keeps its place for `STICKY` unless more important stories push it
  out, so cards don't come and go every hour.
- If Gemini fails, last run's cards stay (while still recent) instead of vanishing.
- Stories that drop off move to `past_top_stories` for `PAST_WINDOW`, shown on the dashboard
  as "Earlier top stories".

Stories are matched across runs by shared items, since their headlines are rewritten each run.
"""

from datetime import datetime, timedelta

from scraper.editor import MAX_STORIES, is_recent
from scraper.models import NewsItem, TopStory

STICKY = timedelta(hours=3)
PAST_WINDOW = timedelta(hours=48)
MAX_PAST = 10


def _same(a: TopStory, b: TopStory) -> bool:
    return not set(a.item_ids).isdisjoint(b.item_ids)


def settle_top_stories(
    fresh: list[TopStory],
    previous: list[TopStory],
    previous_past: list[TopStory],
    items: list[NewsItem],
    now: datetime,
    gemini_answered: bool,
) -> tuple[list[TopStory], list[TopStory]]:
    """Combine this run's picks with last run's. Returns (top stories, past top stories)."""
    by_id = {i.id: i for i in items}

    def members(story: TopStory) -> list[NewsItem]:
        return [by_id[i] for i in story.item_ids if i in by_id and by_id[i].review == "kept"]

    def still_valid(story: TopStory) -> bool:
        found = members(story)
        return len(found) == len(story.item_ids) and is_recent(found, now)

    def score(story: TopStory) -> int:
        return max((m.importance or 0 for m in members(story)), default=0)

    def first_shown(story: TopStory) -> datetime:
        earlier = next((p for p in [*previous, *previous_past] if _same(p, story)), None)
        return (earlier.first_shown if earlier else None) or now

    fresh = [s.model_copy(update={"first_shown": first_shown(s)}) for s in fresh if still_valid(s)]

    # Last run's cards that this run didn't pick: all of them if Gemini failed, otherwise
    # those first shown within STICKY.
    carried = [
        p for p in previous
        if still_valid(p)
        and not any(_same(p, s) for s in fresh)
        and (not gemini_answered or now - (p.first_shown or now) < STICKY)
    ]

    def rank(stories: list[TopStory]) -> list[TopStory]:
        return sorted(stories, key=score, reverse=True)  # stable: fresh before carried on ties

    multi = rank([s for s in [*fresh, *carried] if len(s.item_ids) > 1])
    single = rank([s for s in [*fresh, *carried] if len(s.item_ids) == 1])
    top = [s.model_copy(update={"last_shown": now}) for s in [*multi, *single][:MAX_STORIES]]

    # Everything recently shown that isn't a top story now, newest first, one entry per story.
    past: list[TopStory] = []
    for story in [*previous, *previous_past]:
        shown = story.last_shown or story.first_shown
        if (
            shown is not None
            and now - shown < PAST_WINDOW
            and members(story)
            and not any(_same(story, s) for s in [*top, *past])
        ):
            past.append(story)
    past.sort(key=lambda s: s.last_shown or s.first_shown or now, reverse=True)
    return top, past[:MAX_PAST]
