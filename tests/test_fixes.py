from cite_check.fixes import build_corrected_bibtex, build_fix
from cite_check.models import Reference, ScholarRecord

REF = Reference(
    key="devlin2019bert",
    raw=(
        "@inproceedings{devlin2019bert,\n"
        " author = {Jacob Devlin and Ming-Wei Chang},\n"
        " title = {BERT: Pre-training of Deep Bidirectional Transformers for Language "
        "Understanding},\n"
        " booktitle = {NAACL},\n"
        " pages = {4171--4186},\n"
        " year = {2017}\n}"
    ),
    title="BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
    authors=["Jacob Devlin", "Ming-Wei Chang"],
    year=2017,
    venue="NAACL",
    source="bibtex",
)

RECORD = ScholarRecord(
    title="BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
    authors=["Jacob Devlin", "Ming-Wei Chang", "Kenton Lee", "Kristina Toutanova"],
    year=2019,
    venue="NAACL",
    backend="fake",
)

YEAR_DIFF = {"year": ("2017", "2019")}


def test_fix_corrects_disputed_field_only():
    fix = build_fix(REF, RECORD, YEAR_DIFF)
    assert fix.corrected_fields == {"year": "2019"}
    assert "year" in fix.note


def test_corrected_bibtex_preserves_key_and_type():
    bibtex = build_corrected_bibtex(REF, RECORD, YEAR_DIFF)
    assert bibtex.startswith("@inproceedings{devlin2019bert,")
    assert "year = {2019}" in bibtex
    # undisputed fields keep the cited values
    assert "Jacob Devlin and Ming-Wei Chang" in bibtex
    assert "booktitle = {NAACL}" in bibtex


def test_corrected_bibtex_keeps_fields_it_does_not_model():
    bibtex = build_corrected_bibtex(REF, RECORD, YEAR_DIFF)
    assert "pages = {4171--4186}" in bibtex  # not dropped by the rewrite
    assert "2017" not in bibtex


def test_wrong_doi_is_dropped_from_fix():
    ref = REF.model_copy(
        update={"raw": REF.raw.replace("year = {2017}", "year = {2017},\n doi = {10.1/x}")}
    )
    bibtex = build_corrected_bibtex(ref, RECORD, {"doi": ("10.1/x", "resolves to ...")})
    assert "doi" not in bibtex


def test_author_fix_uses_scholar_authors():
    diffs = {"authors": ("John Smith; Mary Jones", "Jacob Devlin; Ming-Wei Chang")}
    fix = build_fix(REF, RECORD, diffs)
    assert fix.corrected_fields["author"].startswith("Jacob Devlin and Ming-Wei Chang")
    assert "Kenton Lee" in fix.corrected_fields["author"]


def test_pdf_reference_gets_no_bibtex():
    pdf_ref = REF.model_copy(update={"source": "pdf", "raw": "[4] J. Devlin..."})
    fix = build_fix(pdf_ref, RECORD, YEAR_DIFF)
    assert fix.corrected_bibtex is None
    assert fix.corrected_fields == {"year": "2019"}
