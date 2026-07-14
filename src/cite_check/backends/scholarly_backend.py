"""Free Google Scholar backend via the `scholarly` scraper (low volume, may get blocked)."""

import itertools
from typing import Any

from cite_check.backends.base import BackendError
from cite_check.models import ScholarRecord
from cite_check.normalize import extract_year
from cite_check.ratelimit import RateLimiter


def _authors(bib: dict[str, Any]) -> list[str]:
    raw = bib.get("author", [])
    if isinstance(raw, str):
        raw = raw.split(" and ")
    return [a.strip() for a in raw if a and a.strip()]


class ScholarlyBackend:
    name = "scholarly"

    def __init__(self, limiter: RateLimiter | None = None) -> None:
        self._limiter = limiter

    def search(self, query: str, limit: int = 5) -> list[ScholarRecord]:
        from scholarly import scholarly  # lazy: heavy import, only needed on cache miss

        if self._limiter is not None:
            self._limiter.wait()
        try:
            results = list(itertools.islice(scholarly.search_pubs(query), limit))
        except Exception as exc:
            raise BackendError(
                f"scholarly query failed — Google Scholar may be blocking requests. "
                f"Consider --backend serpapi. ({exc})"
            ) from exc

        records = []
        for result in results:
            bib = result.get("bib", {})
            title = bib.get("title")
            if not title:
                continue
            year_raw = str(bib.get("pub_year", ""))
            records.append(
                ScholarRecord(
                    title=title,
                    authors=_authors(bib),
                    year=extract_year(year_raw),
                    venue=bib.get("venue") or None,
                    url=result.get("pub_url"),
                    cited_by=result.get("num_citations"),
                    backend=self.name,
                )
            )
        return records
