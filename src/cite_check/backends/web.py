"""Reachability check for cited web resources (blogs, model cards, project pages)."""

import httpx

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cite-check)"}


def url_status(url: str, client: httpx.Client | None = None) -> int | None:
    """HTTP status after redirects, or None if the host is unreachable."""
    http = client or httpx.Client(timeout=20, follow_redirects=True, headers=_HEADERS)
    try:
        response = http.head(url)
        if response.status_code in (403, 405, 501):  # some servers refuse HEAD
            response = http.get(url)
        return response.status_code
    except httpx.HTTPError:
        return None
