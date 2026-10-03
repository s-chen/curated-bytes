import pytest

from scraper.filters import apply_rules, exclusion_reason

from conftest import NOW, make_item


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/someone/project",
        "https://www.github.com/someone/project",
        "https://gist.github.com/someone/abc",
        "https://gitlab.com/someone/project",
        "https://codeberg.org/someone/project",
    ],
)
def test_code_hosting_links_are_excluded(url):
    assert exclusion_reason(make_item("x", NOW, url=url)) == "code hosting"


@pytest.mark.parametrize(
    "title",
    [
        "The best early October Prime Day deals happening now",
        "The Best Early Amazon Echo Deals (and the Worst) Ahead of Prime Big Deal Days",
        "Affected by layoffs? Don’t miss this $75 deal for your TechCrunch Disrupt 2026 Expo+ Pass",
        "Black Friday 2026: what to expect",
        "Get 40% off a VPN this week",
        "$50 off the Pixel 11",
        "Our favourite promo codes for October",
        "The 2026 gift guide for developers",
        "The Steam Deck is on sale again",
    ],
)
def test_promotional_titles_are_excluded(title):
    assert exclusion_reason(make_item("x", NOW, title=title)) == "promotion"


@pytest.mark.parametrize(
    "title",
    [
        "Sopra Steria widens legal challenge to Capita's Whitehall outsourcing deal",
        "Amazon’s $1B plan to combat data center backlash draws more backlash",
        "Microsoft closes deal to buy a games studio",
        "The 7-year-old Nvidia Shield TV is now $100 more expensive due to AI",
        "Why sales of EVs are slowing",
    ],
)
def test_ordinary_news_is_not_excluded(title):
    assert exclusion_reason(make_item("x", NOW, title=title)) is None


def test_github_blog_is_not_a_code_host():
    assert exclusion_reason(make_item("x", NOW, url="https://github.blog/news/x")) is None


def test_apply_rules_only_touches_pending_items():
    promo = "Huge Black Friday savings"
    items = [
        make_item("p", NOW, title=promo),
        make_item("k", NOW, title=promo, review="kept"),
        make_item("ok", NOW),
    ]
    out, excluded = apply_rules(items)
    assert [i.review for i in out] == ["excluded", "kept", "pending"]
    assert excluded == {"p": "promotion"}
