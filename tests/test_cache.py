from cite_check.backends import CachedBackend
from cite_check.cache import QueryCache
from cite_check.models import ScholarRecord


def make_record(title="T"):
    return ScholarRecord(title=title, authors=["A B"], year=2020, venue="V", backend="fake")


def test_roundtrip(tmp_path):
    cache = QueryCache(tmp_path / "cache.db")
    assert cache.get("fake", "q") is None
    cache.put("fake", "q", [make_record()])
    got = cache.get("fake", "q")
    assert got is not None and got[0].title == "T"
    cache.close()


def test_clear(tmp_path):
    cache = QueryCache(tmp_path / "cache.db")
    cache.put("fake", "q", [make_record()])
    assert cache.clear() == 1
    assert cache.get("fake", "q") is None
    cache.close()


class EmptyBackend:
    name = "empty"

    def __init__(self):
        self.calls = 0

    def search(self, query, limit=5):
        self.calls += 1
        return []


def test_empty_results_are_not_cached(tmp_path):
    from cite_check.backends import CachedBackend

    inner = EmptyBackend()
    cache = QueryCache(tmp_path / "cache.db")
    backend = CachedBackend(inner, cache)
    backend.search("q")
    backend.search("q")
    assert inner.calls == 2  # a transient empty result must not make NOT_FOUND sticky
    cache.close()


def test_cached_backend_hits_inner_once(tmp_path, fake_backend):
    cache = QueryCache(tmp_path / "cache.db")
    backend = CachedBackend(fake_backend, cache)
    first = backend.search("attention is all you need", 3)
    second = backend.search("attention is all you need", 3)
    assert fake_backend.calls == 1
    assert [r.title for r in first] == [r.title for r in second]
    cache.close()
