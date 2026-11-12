"""Identifier checks, fallbacks, and web resources (engine-level, network-free)."""

import httpx
import respx

from cite_check.backends.arxiv import API_URL, ArxivBackend
from cite_check.engine import VerificationEngine
from cite_check.matching import author_score, year_score
from cite_check.models import Reference, ScholarRecord, VerificationStatus
from cite_check.normalize import extract_arxiv_id, extract_url

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2207.12598v1</id>
    <published>2022-07-26T00:00:00Z</published>
    <title>Classifier-Free Diffusion
      Guidance</title>
    <author><name>Jonathan Ho</name></author>
    <author><name>Tim Salimans</name></author>
  </entry>
</feed>"""

CFG = ScholarRecord(
    title="Classifier-Free Diffusion Guidance",
    authors=["Jonathan Ho", "Tim Salimans"],
    year=2022,
    venue="arXiv",
    backend="arxiv",
    preprint=True,
)


def ref(**kw):
    base = dict(
        key="k",
        raw="@article{k,}",
        title="Classifier-Free Diffusion Guidance",
        authors=["Jonathan Ho", "Tim Salimans"],
        year=2022,
        source="bibtex",
    )
    return Reference(**{**base, **kw})


class Static:
    """Backend returning fixed records; counts calls."""

    def __init__(self, records, name="static"):
        self.records, self.name, self.calls = records, name, 0

    def search(self, query, limit=5):
        self.calls += 1
        return list(self.records)

    def by_id(self, arxiv_id):
        return self.records[0] if self.records else None

    def by_doi(self, doi):
        return self.records[0] if self.records else None


@respx.mock
def test_arxiv_backend_parses_atom():
    respx.get(API_URL).mock(return_value=httpx.Response(200, text=ATOM))
    rec = ArxivBackend().by_id("2207.12598")
    assert rec is not None
    assert rec.title == "Classifier-Free Diffusion Guidance"  # whitespace collapsed
    assert rec.authors == ["Jonathan Ho", "Tim Salimans"]
    assert rec.year == 2022 and rec.preprint and rec.backend == "arxiv"


def test_extract_identifiers():
    assert extract_arxiv_id("arXiv preprint arXiv:2207.12598") == "2207.12598"
    assert extract_arxiv_id("https://arxiv.org/abs/2502.14786v2") == "2502.14786"
    assert extract_arxiv_id("Journal of ML") is None
    assert (
        extract_url(r"\url{https://deepmind.google/models/x/}")
        == "https://deepmind.google/models/x/"
    )


def test_arxiv_id_pointing_to_other_paper_is_mismatch():
    other = CFG.model_copy(update={"title": "Denoising Diffusion Probabilistic Models"})
    engine = VerificationEngine(backend=Static([CFG]), arxiv=Static([other]))
    result = engine.verify_one(ref(arxiv_id="2006.11239"))
    assert result.status == VerificationStatus.MISMATCH
    assert "different paper" in result.field_diffs["arxiv"][1]


def test_doi_pointing_to_other_paper_is_mismatch():
    other = CFG.model_copy(update={"title": "Something Else Entirely", "backend": "crossref"})
    engine = VerificationEngine(backend=Static([CFG]), crossref=Static([other]))
    result = engine.verify_one(ref(doi="10.1/x"))
    assert result.status == VerificationStatus.MISMATCH
    assert "doi" in result.field_diffs


def test_fallback_used_only_when_primary_finds_nothing():
    fallback = Static([CFG], name="arxiv")
    result = VerificationEngine(backend=Static([]), fallbacks=[fallback]).verify_one(ref())
    assert result.status == VerificationStatus.VERIFIED
    assert result.best_match.backend == "arxiv"

    fallback.calls = 0
    VerificationEngine(backend=Static([CFG]), fallbacks=[fallback]).verify_one(ref())
    assert fallback.calls == 0


def test_no_primary_backend_runs_on_fallbacks():
    engine = VerificationEngine(backend=None, fallbacks=[Static([CFG])])
    assert engine.verify_one(ref()).status == VerificationStatus.VERIFIED


def test_live_web_resource_is_web_only():
    web = ref(
        title="Genie 2: A Large-Scale Foundation World Model",
        entry_type="misc",
        url="https://deepmind.google/x",
    )
    engine = VerificationEngine(backend=Static([]), url_checker=lambda url: 200)
    assert engine.verify_one(web).status == VerificationStatus.WEB_ONLY

    dead = VerificationEngine(backend=Static([]), url_checker=lambda url: 404).verify_one(web)
    assert dead.status == VerificationStatus.NOT_FOUND
    assert "404" in dead.note


def test_paper_entry_with_url_is_not_excused_as_web():
    paper = ref(title="A Fabricated Paper", entry_type="inproceedings", url="https://x.org")
    engine = VerificationEngine(backend=Static([]), url_checker=lambda url: 200)
    assert engine.verify_one(paper).status == VerificationStatus.NOT_FOUND


def test_author_score_tolerates_swapped_given_family():
    # Crossref stores some names family-first without a comma (RoFormer)
    cited = ["Jianlin Su", "Ahmed Murtadha", "Bo Wen"]
    found = ["Jianlin Su", "Murtadha Ahmed", "Wen Bo"]
    assert author_score(cited, found) == 100.0


def test_preprint_year_may_precede_publication():
    assert year_score(2023, 2022, preprint=True) == 100.0  # arXiv 2022 -> ICLR 2023
    assert year_score(2021, 2022, preprint=True) == 70.0  # cited *before* posting: suspicious
    assert year_score(2023, 2022) == 70.0
