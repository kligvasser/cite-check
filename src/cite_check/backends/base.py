"""Backend protocol and the caching wrapper every backend runs behind."""

from typing import Protocol, runtime_checkable

from cite_check.cache import QueryCache
from cite_check.models import ScholarRecord


class BackendError(RuntimeError):
    """A backend query failed (network error, blocked, bad API key...)."""


# transient HTTP statuses worth retrying with backoff (esp. Semantic Scholar's 429)
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503})


@runtime_checkable
class ScholarBackend(Protocol):
    name: str

    def search(self, query: str, limit: int = 5) -> list[ScholarRecord]: ...


class CachedBackend:
    """Serve queries from the SQLite cache; only cache-misses hit the inner backend."""

    def __init__(self, inner: ScholarBackend, cache: QueryCache) -> None:
        self._inner = inner
        self._cache = cache
        self.name = inner.name

    def search(self, query: str, limit: int = 5) -> list[ScholarRecord]:
        cached = self._cache.get(self.name, query)
        if cached is not None:
            return cached[:limit]
        records = self._inner.search(query, limit)
        # never cache empty results: a transient hiccup would make NOT_FOUND sticky
        if records:
            self._cache.put(self.name, query, records)
        return records
