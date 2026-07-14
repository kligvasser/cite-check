"""Optional GROBID reference parser — academic-grade accuracy for hard PDFs (plan §4.1, phase B).

Requires a running GROBID server, e.g.:
    docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

from cite_check.models import Reference
from cite_check.normalize import clean_text, extract_year

_TEI = {"tei": "http://www.tei-c.org/ns/1.0"}


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = "".join(element.itertext()).strip()
    return value or None


def _parse_bibl_struct(bibl: ET.Element, index: int) -> Reference | None:
    title = _text(bibl.find(".//tei:analytic/tei:title", _TEI)) or _text(
        bibl.find(".//tei:monogr/tei:title", _TEI)
    )
    if not title:
        return None

    authors = []
    for pers in bibl.findall(".//tei:author/tei:persName", _TEI):
        forename = _text(pers.find("tei:forename", _TEI)) or ""
        surname = _text(pers.find("tei:surname", _TEI)) or ""
        name = f"{forename} {surname}".strip()
        if name:
            authors.append(name)

    date = bibl.find(".//tei:imprint/tei:date", _TEI)
    year = extract_year(date.get("when", "")) if date is not None else None
    venue = None
    if bibl.find(".//tei:analytic/tei:title", _TEI) is not None:
        venue = _text(bibl.find(".//tei:monogr/tei:title", _TEI))
    doi_el = bibl.find(".//tei:idno[@type='DOI']", _TEI)

    return Reference(
        key=f"ref-{index}",
        raw=clean_text("".join(bibl.itertext())),
        title=clean_text(title),
        authors=authors,
        year=year,
        venue=clean_text(venue) if venue else None,
        doi=_text(doi_el),
        source="pdf",
    )


class GrobidClient:
    def __init__(self, base_url: str = "http://localhost:8070", timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def parse_references(self, pdf_path: str | Path) -> list[Reference]:
        with open(pdf_path, "rb") as fh:
            response = httpx.post(
                f"{self._base_url}/api/processReferences",
                files={"input": fh},
                timeout=self._timeout,
            )
        response.raise_for_status()
        root = ET.fromstring(response.text)
        bibls = root.findall(".//tei:biblStruct", _TEI)
        refs = [_parse_bibl_struct(b, i) for i, b in enumerate(bibls, start=1)]
        return [r for r in refs if r is not None]
