"""arXiv — free official API: id lookup + title search (fallback when Scholar is blocked).

arXiv asks API clients to wait ~3 s between requests; pass a matching RateLimiter.
"""

import re
import xml.etree.ElementTree as ET

import httpx

from cite_check.backends.base import RETRYABLE_STATUSES, BackendError
from cite_check.models import ScholarRecord
from cite_check.normalize import extract_year
from cite_check.ratelimit import RateLimiter, with_retries

API_URL = "https://export.arxiv.org/api/query"
_NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
_ID_RE = re.compile(r"abs/(.+?)(?:v\d+)?$")


def _text(el: ET.Element | None) -> str:
    return " ".join((el.text or "").split()) if el is not None else ""


def _record_from_entry(entry: ET.Element) -> ScholarRecord | None:
    title = _text(entry.find("a:title", _NS))
    if not title or title == "Error":
        return None
    authors = [_text(a) for a in entry.findall("a:author/a:name", _NS)]
    journal_ref = _text(entry.find("arxiv:journal_ref", _NS)) or None
    return ScholarRecord(
        title=title,
        authors=[a for a in authors if a],
        year=extract_year(_text(entry.find("a:published", _NS))),
        venue=journal_ref or "arXiv",
        url=_text(entry.find("a:id", _NS)) or None,
        backend="arxiv",
        preprint=True,
    )


def arxiv_id_of(record: ScholarRecord) -> str | None:
    match = _ID_RE.search(record.url or "")
    return match.group(1) if match else None


class ArxivBackend:
    name = "arxiv"

    def __init__(
        self, limiter: RateLimiter | None = None, client: httpx.Client | None = None
    ) -> None:
        self._limiter = limiter
        self._client = client or httpx.Client(timeout=60, follow_redirects=True)

    def _query(self, params: dict[str, str | int]) -> list[ScholarRecord]:
        if self._limiter is not None:
            self._limiter.wait()

        def _get() -> httpx.Response:
            response = self._client.get(API_URL, params=params)
            if response.status_code in RETRYABLE_STATUSES:
                response.raise_for_status()
            return response

        try:
            response = with_retries(_get, tries=3, base_s=3.0)
            response.raise_for_status()
            root = ET.fromstring(response.content)
        except (httpx.HTTPError, ET.ParseError) as exc:
            raise BackendError(f"arXiv request failed: {exc}") from exc
        records = [_record_from_entry(e) for e in root.findall("a:entry", _NS)]
        return [r for r in records if r is not None]

    def by_id(self, arxiv_id: str) -> ScholarRecord | None:
        """Resolve an arXiv id to its record; None if arXiv doesn't know it."""
        records = self._query({"id_list": arxiv_id, "max_results": 1})
        return records[0] if records else None

    def search(self, query: str, limit: int = 5) -> list[ScholarRecord]:
        """Title phrase search. ``query`` should be a bare title (quotes are stripped)."""
        words = re.sub(r"[^\w\s]", " ", query).split()
        if not words:
            return []
        return self._query({"search_query": f'ti:"{" ".join(words)}"', "max_results": limit})
