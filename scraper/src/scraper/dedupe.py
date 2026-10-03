"""URL normalisation and ID generation for deduplication."""

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that only track the click and don't change the article.
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_DEFAULT_PORTS = {"http": ":80", "https": ":443"}


def normalise_url(url: str) -> str:
    """Canonicalise a URL so trivially different links to one article match.

    Treats http and https as the same, lowercases the host, and drops the default port,
    fragment, tracking params and any trailing slash on the path. Remaining query params
    are sorted. The result is a dedupe key, not a link to display.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    default_port = _DEFAULT_PORTS.get(scheme)
    if default_port and netloc.endswith(default_port):
        netloc = netloc[: -len(default_port)]
    if scheme == "http":
        scheme = "https"

    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith(_TRACKING_PREFIXES)
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def item_id(url: str) -> str:
    """MD5 of the normalised URL. Used as the dedupe key, not for security."""
    return hashlib.md5(normalise_url(url).encode("utf-8")).hexdigest()
