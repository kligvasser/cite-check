"""Full pipeline over the benchmark corpus (plan §6): parse -> verify -> fix -> report."""

import json
from pathlib import Path

from cite_check.engine import VerificationEngine
from cite_check.ingest import parse_bibtex
from cite_check.models import VerificationStatus
from cite_check.report import build_fixed_bib, summarize, to_json, to_markdown

CORPUS = Path(__file__).parent / "fixtures" / "corpus.bib"

EXPECTED = {
    "vaswani2017": VerificationStatus.VERIFIED,
    "he2016": VerificationStatus.VERIFIED,
    "goodfellow2014": VerificationStatus.VERIFIED,
    "devlin2019bert": VerificationStatus.MISMATCH,
    "kingma2015adam": VerificationStatus.MISMATCH,
    "doe2021quantum": VerificationStatus.NOT_FOUND,
}


def run_corpus(fake_backend):
    refs = parse_bibtex(CORPUS)
    engine = VerificationEngine(backend=fake_backend)
    return engine.verify_all(refs)


def test_corpus_classification(fake_backend):
    results = {r.reference.key: r for r in run_corpus(fake_backend)}
    assert len(results) == len(EXPECTED)
    for key, expected_status in EXPECTED.items():
        assert results[key].status == expected_status, (
            f"{key}: expected {expected_status}, got {results[key].status}"
        )


def test_wrong_year_gets_year_fix(fake_backend):
    results = {r.reference.key: r for r in run_corpus(fake_backend)}
    bert = results["devlin2019bert"]
    assert bert.field_diffs.get("year") == ("2017", "2019")
    assert bert.suggested_fix is not None
    assert bert.suggested_fix.corrected_fields == {"year": "2019"}
    assert "year = {2019}" in bert.suggested_fix.corrected_bibtex


def test_wrong_authors_get_author_fix(fake_backend):
    results = {r.reference.key: r for r in run_corpus(fake_backend)}
    adam = results["kingma2015adam"]
    assert "authors" in adam.field_diffs
    assert adam.suggested_fix.corrected_fields["author"] == "Diederik P. Kingma and Jimmy Ba"


def test_engine_survives_broken_backend():
    from cite_check.models import VerificationStatus as VS

    class ExplodingBackend:
        name = "boom"

        def search(self, query, limit=5):
            raise RuntimeError("kaboom")  # not a BackendError: unexpected failure

    refs = parse_bibtex(CORPUS)
    results = VerificationEngine(backend=ExplodingBackend()).verify_all(refs)
    assert len(results) == len(refs)
    assert all(r.status == VS.ERROR for r in results)
    assert "kaboom" in (results[0].note or "")


def test_report_outputs(fake_backend):
    results = run_corpus(fake_backend)

    counts = summarize(results)
    assert counts[VerificationStatus.VERIFIED] == 3
    assert counts[VerificationStatus.MISMATCH] == 2
    assert counts[VerificationStatus.NOT_FOUND] == 1

    payload = json.loads(to_json(results))
    assert len(payload) == 6
    assert payload[0]["status"] == "VERIFIED"

    markdown = to_markdown(results)
    assert "MISMATCH: devlin2019bert" in markdown
    assert "```bibtex" in markdown

    fixed = build_fixed_bib(results)
    assert "year = {2019}" in fixed  # corrected entry substituted
    assert "@article{vaswani2017" in fixed  # verified entries keep their raw block
