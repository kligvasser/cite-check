import httpx
import pytest
import respx

from cite_check.backends import (
    BackendError,
    CrossrefBackend,
    SemanticScholarBackend,
    SerpApiBackend,
)
from cite_check.backends.serpapi import BASE_URL as SERPAPI_URL

SERPAPI_PAYLOAD = {
    "organic_results": [
        {
            "title": "Attention is all you need",
            "link": "https://papers.nips.cc/paper/7181",
            "publication_info": {
                "summary": (
                    "A Vaswani, N Shazeer, N Parmar - Advances in neural information "
                    "processing systems, 2017 - proceedings.neurips.cc"
                )
            },
            "inline_links": {"cited_by": {"total": 100000}},
        }
    ]
}


@respx.mock
def test_serpapi_parses_results():
    respx.get(SERPAPI_URL).mock(return_value=httpx.Response(200, json=SERPAPI_PAYLOAD))
    records = SerpApiBackend("key").search('"Attention is all you need"', 3)
    assert len(records) == 1
    rec = records[0]
    assert rec.title == "Attention is all you need"
    assert rec.authors == ["A Vaswani", "N Shazeer", "N Parmar"]
    assert rec.year == 2017
    assert "Advances in neural information" in rec.venue
    assert rec.cited_by == 100000
    assert rec.backend == "serpapi"


@respx.mock
def test_serpapi_error_payload_raises():
    respx.get(SERPAPI_URL).mock(return_value=httpx.Response(200, json={"error": "Invalid API key"}))
    with pytest.raises(BackendError, match="Invalid API key"):
        SerpApiBackend("bad").search("q")


def test_serpapi_requires_key():
    with pytest.raises(BackendError, match="API key"):
        SerpApiBackend("")


@respx.mock
def test_crossref_by_doi():
    respx.get("https://api.crossref.org/works/10.1109/CVPR.2016.90").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {
                    "title": ["Deep Residual Learning for Image Recognition"],
                    "author": [{"given": "Kaiming", "family": "He"}],
                    "issued": {"date-parts": [[2016, 6]]},
                    "container-title": ["2016 IEEE Conference on CVPR"],
                    "URL": "https://doi.org/10.1109/cvpr.2016.90",
                    "is-referenced-by-count": 150000,
                }
            },
        )
    )
    rec = CrossrefBackend().by_doi("10.1109/CVPR.2016.90")
    assert rec is not None
    assert rec.title == "Deep Residual Learning for Image Recognition"
    assert rec.authors == ["Kaiming He"]
    assert rec.year == 2016
    assert rec.backend == "crossref"


@respx.mock
def test_crossref_unknown_doi_returns_none():
    respx.get("https://api.crossref.org/works/10.9999/nope").mock(return_value=httpx.Response(404))
    assert CrossrefBackend().by_doi("10.9999/nope") is None


@respx.mock
def test_semantic_scholar_search():
    respx.get("https://api.semanticscholar.org/graph/v1/paper/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "title": "Generative Adversarial Nets",
                        "authors": [{"name": "Ian Goodfellow"}],
                        "year": 2014,
                        "venue": "NeurIPS",
                        "url": "https://www.semanticscholar.org/paper/abc",
                        "citationCount": 60000,
                    }
                ]
            },
        )
    )
    records = SemanticScholarBackend().search("Generative Adversarial Nets")
    assert records[0].title == "Generative Adversarial Nets"
    assert records[0].year == 2014
    assert records[0].backend == "semantic_scholar"
