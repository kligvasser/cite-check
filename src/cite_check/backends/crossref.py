"""Crossref — DOI resolution and free bibliographic search for corroboration (plan §2)."""

from typing import Any

import httpx

from cite_check.backends.base import BackendError
from cite_check.models import ScholarRecord
from cite_check.ratelimit import RateLimiter

WORKS_URL = "https://api.crossref.org/works"


def _record_from_work(work: dict[str, Any]) -> ScholarRecord | None:
    titles = work.get("title") or []
    if not titles:
        return None
    authors = [
        " ".join(part for part in (a.get("given"), a.get("family")) if part)
        for a in work.get("author", [])
    ]
    date_parts = (work.get("issued") or {}).get("date-parts") or [[None]]
    year = date_parts[0][0] if date_parts[0] else None
    container = work.get("container-title") or []
    return ScholarRecord(
        title=titles[0],
        authors=[a for a in authors if a],
        year=year,
        venue=container[0] if container else None,
        url=work.get("URL"),
        cited_by=work.get("is-referenced-by-count"),
        backend="crossref",
    )


class CrossrefBackend:
    name = "crossref"

    def __init__(
        self, limiter: RateLimiter | None = None, client: httpx.Client | None = None
    ) -> None:
        self._limiter = limiter
        self._client = client or httpx.Client(timeout=30)

    def by_doi(self, doi: str) -> ScholarRecord | None:
        """Resolve a DOI to its Crossref record; None if the DOI is unknown."""
        if self._limiter is not None:
            self._limiter.wait()
        try:
            response = self._client.get(f"{WORKS_URL}/{doi}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            work = response.json().get("message", {})
        except httpx.HTTPError as exc:
            raise BackendError(f"Crossref DOI lookup failed: {exc}") from exc
        return _record_from_work(work)

    def search(self, query: str, limit: int = 5) -> list[ScholarRecord]:
        if self._limiter is not None:
            self._limiter.wait()
        try:
            response = self._client.get(
                WORKS_URL, params={"query.bibliographic": query, "rows": limit}
            )
            response.raise_for_status()
            items = response.json().get("message", {}).get("items", [])
        except httpx.HTTPError as exc:
            raise BackendError(f"Crossref search failed: {exc}") from exc
        records = [_record_from_work(work) for work in items[:limit]]
        return [r for r in records if r is not None]
