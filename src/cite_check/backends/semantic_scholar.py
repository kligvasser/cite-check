"""Semantic Scholar — free official API used to corroborate Scholar results (plan §2)."""

import httpx

from cite_check.backends.base import RETRYABLE_STATUSES, BackendError
from cite_check.models import ScholarRecord
from cite_check.ratelimit import RateLimiter, with_retries

SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "title,authors,year,venue,url,citationCount"


class SemanticScholarBackend:
    name = "semantic_scholar"

    def __init__(
        self, limiter: RateLimiter | None = None, client: httpx.Client | None = None
    ) -> None:
        self._limiter = limiter
        self._client = client or httpx.Client(timeout=30)

    def search(self, query: str, limit: int = 5) -> list[ScholarRecord]:
        if self._limiter is not None:
            self._limiter.wait()

        def _get() -> httpx.Response:
            response = self._client.get(
                SEARCH_URL, params={"query": query, "limit": limit, "fields": _FIELDS}
            )
            if response.status_code in RETRYABLE_STATUSES:  # free tier 429s often
                response.raise_for_status()
            return response

        try:
            response = with_retries(_get, tries=3, base_s=2.0)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise BackendError(f"Semantic Scholar request failed: {exc}") from exc

        records = []
        for paper in data.get("data", [])[:limit]:
            title = paper.get("title")
            if not title:
                continue
            records.append(
                ScholarRecord(
                    title=title,
                    authors=[a["name"] for a in paper.get("authors", []) if a.get("name")],
                    year=paper.get("year"),
                    venue=paper.get("venue") or None,
                    url=paper.get("url"),
                    cited_by=paper.get("citationCount"),
                    backend=self.name,
                )
            )
        return records
