"""Rule-based exclusions, applied before Gemini sees anything.

These catch the obvious cases cheaply and deterministically. Gemini's review catches the rest.
"""

import re
from urllib.parse import urlsplit

from scraper.models import NewsItem

# Personal code repositories, gists and other code-hosting pages.
CODE_HOSTS = {
    "github.com",
    "gist.github.com",
    "gitlab.com",
    "codeberg.org",
    "bitbucket.org",
    "git.sr.ht",
    "sr.ht",
}

# Shopping and promotional headlines. Narrow on purpose: "Capita's outsourcing deal" or
# "Amazon's $1B plan" must not match. Anything subtler is left to Gemini.
PROMO_PATTERNS = re.compile(
    r"""
      \b(prime\ (big\ deal\ )?days?|black\ friday|cyber\ monday)\b
    | \bbest\b.*\bdeals\b
    | \bdeals?\ (on|for)\ (your|the\ best)\b
    | \bdon[’']t\ miss\ this\b.*\bdeal\b
    | \b\d+%\ off\b
    | \$\d+(\.\d\d)?\ off\b
    | \b(coupon|promo\ code|discount\ code|voucher\ code)s?\b
    | \bgift\ guide\b
    | \bon\ sale\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def exclusion_reason(item: NewsItem) -> str | None:
    host = (urlsplit(item.url).hostname or "").removeprefix("www.")
    if host in CODE_HOSTS:
        return "code hosting"
    if PROMO_PATTERNS.search(item.title):
        return "promotion"
    return None


def apply_rules(items: list[NewsItem]) -> tuple[list[NewsItem], dict[str, str]]:
    """Mark pending items that match a rule as excluded. Returns the items and {id: reason}."""
    excluded: dict[str, str] = {}
    out = []
    for item in items:
        reason = exclusion_reason(item) if item.review == "pending" else None
        if reason:
            excluded[item.id] = reason
            item = item.model_copy(update={"review": "excluded"})
        out.append(item)
    return out, excluded
