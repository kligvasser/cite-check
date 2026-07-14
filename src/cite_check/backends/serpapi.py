"""Paid Google Scholar backend via SerpAPI — the reliable path (plan §2)."""

from typing import Any

import httpx

from cite_check.backends.base import BackendError
from cite_check.models import ScholarRecord
from cite_check.normalize import extract_year
from cite_check.ratelimit import RateLimiter

BASE_URL = "https://serpapi.com/search.json"


def _parse_summary(summary: str) -> tuple[list[str], str | None, int | None]:
    """Parse SerpAPI's ``publication_info.summary``.

    Format: "A Vaswani, N Shazeer - Advances in neural info..., 2017 - proceedings.neurips.cc"
    """
    parts = [p.strip() for p in summary.split(" - ")]
    authors = [a.strip() for a in parts[0].split(",") if a.strip()] if parts else []
    venue: str | None = None
    year: int | None = None
    if len(parts) > 1:
        venue_year = parts[1]
        year = extract_year(venue_year)
        venue = venue_year.rsplit(",", 1)[0].strip() if "," in venue_year else venue_year
        venue = venue or None
    return authors, venue, year


class SerpApiBackend:
    name = "serpapi"

    def __init__(
        self,
        api_key: str,
        limiter: RateLimiter | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise BackendError(
                "SerpAPI backend needs an API key (set CITECHECK_SERPAPI_KEY or config.toml)."
            )
        self._api_key = api_key
        self._limiter = limiter
        self._client = client or httpx.Client(timeout=30)

    def search(self, query: str, limit: int = 5) -> list[ScholarRecord]:
        if self._limiter is not None:
            self._limiter.wait()
        params: dict[str, str | int] = {
            "engine": "google_scholar",
            "q": query,
            "num": limit,
            "api_key": self._api_key,
        }
        try:
            response = self._client.get(BASE_URL, params=params)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except httpx.HTTPError as exc:
            raise BackendError(f"SerpAPI request failed: {exc}") from exc
        if "error" in data:
            raise BackendError(f"SerpAPI error: {data['error']}")

        records = []
        for item in data.get("organic_results", [])[:limit]:
            title = item.get("title")
            if not title:
                continue
            info = item.get("publication_info", {})
            authors, venue, year = _parse_summary(info.get("summary", ""))
            # structured author list (when present) beats the summary parse
            if info.get("authors"):
                authors = [a["name"] for a in info["authors"] if a.get("name")]
            cited_by = item.get("inline_links", {}).get("cited_by", {}).get("total")
            records.append(
                ScholarRecord(
                    title=title,
                    authors=authors,
                    year=year,
                    venue=venue,
                    url=item.get("link"),
                    cited_by=cited_by,
                    backend=self.name,
                )
            )
        return records
