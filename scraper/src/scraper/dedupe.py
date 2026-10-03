"""URL normalisation and ID generation for deduplication."""

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that only track the click and don't change the article.
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {"ref", "fbclid", "gclid", "mc_cid", "mc_eid"}


def normalise_url(url: str) -> str:
    """Canonicalise a URL so trivially different links to one article match.

    Lowercases the scheme and host, drops the fragment, tracking params and any
    trailing slash on the path.
    """
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def item_id(url: str) -> str:
    """MD5 of the normalised URL. Used as the dedupe key, not for security."""
    return hashlib.md5(normalise_url(url).encode("utf-8")).hexdigest()
