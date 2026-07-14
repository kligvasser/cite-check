# cite-check — Project Plan

A Python tool that verifies the citations of a written paper. Given a **PDF** or a **BibTeX** file, it extracts every cited reference, verifies each one against **Google Scholar**, reports which citations are correct, which are wrong or unverifiable, and **suggests a fix** (the corrected bibliographic entry) for every problematic citation.

---

## 1. Goals and Non-Goals

### 1.1 Goals

1. Accept two input formats:
   - A `.bib` (BibTeX) file — the structured, easy case.
   - A paper PDF — extract the bibliography/references section and parse it into structured entries.
2. For every extracted reference, query Google Scholar and decide one of:
   - **VERIFIED** — a Scholar record matches the citation (title, authors, year, venue all consistent).
   - **MISMATCH** — a close Scholar record exists but one or more fields disagree (e.g. wrong year, misspelled author, wrong venue). A fix is suggested.
   - **NOT_FOUND** — no plausible Scholar record exists (possibly a fabricated / hallucinated citation, or a very obscure source).
3. For MISMATCH entries, produce a **suggested fix**: the corrected field values and, when the input was BibTeX, a ready-to-paste corrected BibTeX entry.
4. Produce a clear report: terminal table, plus optional JSON and Markdown/HTML report files.
5. Be resilient to Google Scholar's anti-bot measures (rate limiting, caching, retries, pluggable backends).

### 1.2 Non-Goals (v1)

- Checking that in-text citation *usage* is appropriate (i.e. that the cited paper actually supports the claim). Only bibliographic correctness is in scope.
- Checking citation *style/formatting* (APA vs IEEE etc.).
- Plagiarism detection.
- A web UI (CLI first; a UI can come later).

---

## 2. Key Constraint: Google Scholar Access

This is the central technical risk of the project and must be designed around from day one.

- **Google Scholar has no official API.** Automated scraping violates its ToS and is aggressively blocked with CAPTCHAs and IP bans after a small number of requests.
- Practical options, in order of reliability:

| Backend | Cost | Reliability | Notes |
|---|---|---|---|
| **SerpAPI** (Google Scholar engine) | Paid (free tier ~100 searches/mo) | High | Clean JSON, handles CAPTCHAs. Recommended default for real use. |
| **`scholarly`** library | Free | Low–Medium | Scrapes Scholar directly; works for small volumes, breaks under load, needs proxies (e.g. free `FreeProxies` or paid ScraperAPI). |
| Cross-check APIs: **Crossref**, **Semantic Scholar**, **OpenAlex** | Free, official APIs | High | Not Google Scholar, but excellent corroborating sources; Semantic Scholar's index overlaps heavily with Scholar. |

**Design decision:** implement a `ScholarBackend` abstraction with interchangeable implementations (`SerpApiBackend`, `ScholarlyBackend`, and optionally `SemanticScholarBackend` / `CrossrefBackend` as secondary verifiers). Google Scholar remains the primary source of truth per the project requirement; the free official APIs serve as fallback/corroboration when Scholar is unreachable, and can be disabled with a `--scholar-only` flag.

Additionally: **cache every query response on disk** (SQLite) so re-runs never re-hit the network, and apply polite rate limiting (configurable delay + exponential backoff + jitter).

---

## 3. System Architecture

```
                 ┌────────────────────────────────────────────┐
 input.pdf ──►   │ 1. INGESTION                               │
 input.bib ──►   │  PDF → text → references section → entries │
                 │  BibTeX → entries                          │
                 └───────────────┬────────────────────────────┘
                                 │  list[Reference]
                 ┌───────────────▼────────────────────────────┐
                 │ 2. NORMALIZATION                           │
                 │  clean titles/authors/years, dedupe        │
                 └───────────────┬────────────────────────────┘
                                 │  list[Reference]
                 ┌───────────────▼────────────────────────────┐
                 │ 3. VERIFICATION ENGINE                     │
                 │  per reference:                            │
                 │   query ScholarBackend (cache → network)   │
                 │   score candidates (fuzzy matching)        │
                 │   classify: VERIFIED / MISMATCH / NOT_FOUND│
                 └───────────────┬────────────────────────────┘
                                 │  list[VerificationResult]
                 ┌───────────────▼────────────────────────────┐
                 │ 4. FIX SUGGESTION                          │
                 │  build corrected fields + BibTeX entry     │
                 └───────────────┬────────────────────────────┘
                                 │
                 ┌───────────────▼────────────────────────────┐
                 │ 5. REPORTING                               │
                 │  rich terminal table, JSON, Markdown       │
                 └────────────────────────────────────────────┘
```

### 3.1 Core Data Models (pydantic)

```python
class Reference:
    key: str | None          # BibTeX key or generated id (e.g. "ref-17")
    raw: str                 # original raw string (PDF) or raw BibTeX block
    title: str
    authors: list[str]
    year: int | None
    venue: str | None        # journal / conference / publisher
    doi: str | None
    source: Literal["bibtex", "pdf"]

class ScholarRecord:
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    url: str | None
    cited_by: int | None
    backend: str             # which backend produced it

class VerificationResult:
    reference: Reference
    status: Literal["VERIFIED", "MISMATCH", "NOT_FOUND", "ERROR"]
    best_match: ScholarRecord | None
    score: float             # overall 0–100 confidence
    field_diffs: dict[str, tuple[str, str]]   # field → (cited value, scholar value)
    suggested_fix: SuggestedFix | None

class SuggestedFix:
    corrected_fields: dict[str, str]
    corrected_bibtex: str | None
    note: str                # human-readable explanation
```

---

## 4. Component Design

### 4.1 Ingestion

**BibTeX path** (simple, do first):
- Parse with `bibtexparser` (v2).
- Map entries to `Reference`, keeping the raw block for fix generation.
- Handle LaTeX escapes in titles/authors (`{\"o}` → `ö`) via `pylatexenc`.

**PDF path** (harder, phased):
- *Phase A (v1):* extract text with `pymupdf` (fitz), locate the references section by heading heuristics (`References`, `Bibliography`, `REFERENCES`…), split into individual reference strings using numbering/indentation/year-pattern heuristics, then parse each string into fields with **regex + heuristics** (year in parens, quoted or period-delimited title, leading author list).
- *Phase B (v1.1, optional quality upgrade):* support **GROBID** (dockerized) or **anystyle** as a high-accuracy reference parser behind an optional `--parser grobid` flag. GROBID is the academic-grade standard for this exact problem; treating it as optional keeps the base install light.
- Also scan PDF text for embedded DOIs/arXiv IDs — when present, they make verification nearly free and exact.

### 4.2 Normalization

- Unicode-normalize (NFKC), strip LaTeX braces, collapse whitespace, lowercase for comparison keys.
- Author normalization: `"Last, First"` ↔ `"First Last"`, initials handling (`J. Smith` ≈ `John Smith`).
- Dedupe identical references.

### 4.3 Verification Engine

Per reference:

1. **Query strategy** (stop at first confident hit):
   a. If DOI present → resolve DOI directly (Crossref) and confirm the record on Scholar by title.
   b. Query Scholar with the exact title (quoted).
   c. If weak results → query with title + first author + year.
2. **Candidate scoring** — for each of the top N (≈5) Scholar results compute:
   - `title_score` — token-sort fuzzy ratio (`rapidfuzz`), weight ~0.55
   - `author_score` — fraction of cited authors matched by last name + initial, weight ~0.25
   - `year_score` — exact 1.0 / ±1 year 0.7 / else 0.0, weight ~0.15 (Scholar years are noisy: preprint vs published)
   - `venue_score` — fuzzy partial match, weight ~0.05 (venues are abbreviated inconsistently; keep the weight low)
3. **Classification thresholds** (tunable in config):
   - overall ≥ 90 and no field below its own floor → **VERIFIED**
   - best candidate title ≥ 85 but some field disagrees → **MISMATCH** (report exactly which fields, with both values)
   - otherwise → **NOT_FOUND**
4. **Politeness layer**: token-bucket rate limiter (default ~1 request / 3–5 s for `scholarly`), exponential backoff on block detection, and the SQLite cache in front of everything.

### 4.4 Fix Suggestion

- For MISMATCH: take the best Scholar record as ground truth, produce `corrected_fields` (only the fields that differ) and regenerate the full corrected BibTeX entry (preserving the original key).
- For NOT_FOUND: if a *plausible-but-below-threshold* candidate exists (title score 60–85), surface it as "did you mean …?" rather than silently reporting nothing.
- Never auto-modify the user's files in v1 — output fixes to the report and to an optional `fixed.bib` written next to the report (`--emit-fixed-bib`).

### 4.5 Reporting

- **Terminal** (via `rich`): summary line (`42 refs: 37 verified, 3 mismatched, 2 not found`) + a table with status, key, title, score, and the diff for mismatches. Exit code non-zero if any MISMATCH/NOT_FOUND (CI-friendly).
- **JSON** (`--json out.json`): full machine-readable `VerificationResult` dump.
- **Markdown report** (`--report report.md`): human-readable, one section per problematic citation with cited vs. found side-by-side and the suggested BibTeX fix in a code block.

### 4.6 CLI

Built with `typer`:

```
cite-check verify paper.pdf
cite-check verify refs.bib --backend serpapi --json results.json
cite-check verify refs.bib --report report.md --emit-fixed-bib
cite-check verify paper.pdf --parser grobid --scholar-only
cite-check cache clear
```

Config precedence: CLI flags > env vars (`CITECHECK_SERPAPI_KEY`) > `~/.config/cite-check/config.toml` > defaults.

---

## 5. Project Structure

```
cite-check/
├── pyproject.toml            # uv/hatchling; deps + dev extras
├── README.md
├── PLAN.md
├── src/
│   └── cite_check/
│       ├── __init__.py
│       ├── cli.py            # typer app
│       ├── config.py         # settings loading
│       ├── models.py         # pydantic data models
│       ├── ingest/
│       │   ├── bibtex.py     # .bib → list[Reference]
│       │   ├── pdf.py        # .pdf → list[Reference] (heuristic parser)
│       │   └── grobid.py     # optional GROBID client
│       ├── normalize.py
│       ├── backends/
│       │   ├── base.py       # ScholarBackend protocol
│       │   ├── serpapi.py
│       │   ├── scholarly_backend.py
│       │   ├── semantic_scholar.py   # secondary verifier
│       │   └── crossref.py           # DOI resolution + secondary verifier
│       ├── cache.py          # SQLite response cache
│       ├── ratelimit.py
│       ├── matching.py       # scoring + classification
│       ├── fixes.py          # suggested-fix builder
│       └── report.py         # rich / json / markdown outputs
└── tests/
    ├── fixtures/             # sample .bib files, PDF reference sections,
    │                         #   recorded backend JSON responses
    ├── test_bibtex_ingest.py
    ├── test_pdf_ingest.py
    ├── test_normalize.py
    ├── test_matching.py
    ├── test_fixes.py
    └── test_e2e.py           # full pipeline against recorded responses
```

### 5.1 Dependencies

| Purpose | Package |
|---|---|
| CLI | `typer` |
| Data models | `pydantic` |
| BibTeX parsing | `bibtexparser`, `pylatexenc` |
| PDF text extraction | `pymupdf` |
| Fuzzy matching | `rapidfuzz` |
| HTTP | `httpx` |
| Scholar backends | `scholarly` (free), `serpapi` client via httpx (paid) |
| Terminal output | `rich` |
| Testing | `pytest`, `respx` (httpx mocking) |
| Tooling | `uv`, `ruff` (lint+format), `pytest-cov` |

Python ≥ 3.11. Package layout: `src/` layout, installable, entry point `cite-check`.

---

## 6. Testing Strategy

1. **Unit tests, no network**: all backend HTTP interactions are tested against recorded JSON fixtures (`respx` for httpx; canned objects for `scholarly`). The matching engine gets a table-driven test suite: known-good pairs, near-misses (year off by one, swapped author order, subtitle dropped), and clear negatives.
2. **Fixture corpus**: a hand-built `fixtures/corpus.bib` containing ~30 entries: 20 correct well-known papers, 5 with deliberately corrupted fields (wrong year, misspelled author, truncated title), 5 fabricated papers. The e2e test asserts the exact expected classification for each — this doubles as the accuracy benchmark.
3. **PDF parsing tests**: reference-section snippets from a few real papers (IEEE-numbered, APA author-year, arXiv style) as text fixtures; assert the splitter/parser recovers the right number of entries and correct titles.
4. **A single opt-in live test** (`pytest -m live`) that hits the real backend with 2 queries, excluded from CI.

---

## 7. Milestones

**M1 — Skeleton + BibTeX happy path** *(foundation)*
Project scaffolding (`pyproject.toml`, src layout, CI-ready tooling), data models, BibTeX ingestion, normalization, CLI stub that prints parsed references. ✅ *Done when:* `cite-check verify refs.bib --dry-run` lists parsed entries.

**M2 — Verification engine with one backend**
`ScholarBackend` protocol, `scholarly` backend (free path), SQLite cache, rate limiter, matching/scoring, classification, terminal report. ✅ *Done when:* the fixture corpus classifies correctly ≥ 90% with recorded responses, and a small live run works.

**M3 — Fix suggestions + reports**
Field diffs, corrected BibTeX generation, "did you mean" for near-misses, JSON + Markdown reports, `--emit-fixed-bib`, meaningful exit codes. ✅ *Done when:* corrupted fixture entries yield correct suggested fixes.

**M4 — PDF ingestion (heuristic)**
PyMuPDF extraction, references-section detection, entry splitting, field parsing, DOI/arXiv-ID harvesting. ✅ *Done when:* three real sample papers (IEEE, APA, arXiv styles) parse with ≥ 90% of references recovered.

**M5 — Robustness + second backend**
SerpAPI backend, Semantic Scholar / Crossref corroboration (`--scholar-only` opt-out), block detection + backoff, config file support, docs/README, optional GROBID parser. ✅ *Done when:* a 40-reference real paper verifies end-to-end without manual intervention.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Google Scholar blocks/CAPTCHAs the free backend | **High** | Cache aggressively; slow polite rate limit; SerpAPI backend as the reliable path; secondary official APIs for corroboration; clear error message telling the user which knob to turn |
| Scholar ToS concerns with scraping | Medium | Default to conservative rates; document the tradeoff; make the paid API (which handles this) the recommended backend |
| PDF reference parsing accuracy | High | Heuristics first, measured on fixtures; GROBID escape hatch for hard PDFs; always show `raw` string so users can spot parse failures |
| Scholar metadata itself is noisy (wrong years, merged records) | Medium | Soft year matching (±1), low venue weight, corroborate mismatches against Crossref before asserting a fix |
| Non-English / non-CS citations behave differently | Low | Unicode-safe normalization from day one; keep thresholds configurable |

---

## 9. Future Extensions (post-v1)

- In-text citation cross-check: every `\cite{key}` / "[17]" actually resolves to a bibliography entry and vice versa (orphan detection) — cheap and high value.
- LaTeX source (`.tex` + `.bib`) as a first-class input.
- Batch mode over a directory of papers; HTML report.
- GitHub Action for CI on paper repositories.
- Optional LLM assist for parsing messy free-form reference strings.
