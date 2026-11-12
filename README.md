# cite-check

Verify the citations of a written paper — input a **PDF** or a **BibTeX** file — against **Google Scholar** (plus arXiv, Crossref and Semantic Scholar), and get a suggested fix for every incorrect or unverifiable reference.

Each reference is classified as:

- **VERIFIED** — a matching record exists (title, authors, year consistent)
- **MISMATCH** — a close record exists but fields disagree, or the cited DOI / arXiv id
  points to a *different* paper; a corrected entry is suggested
- **NOT_FOUND** — no plausible record exists (possibly fabricated)
- **WEB_ONLY** — a `@misc`/`@online` web resource (blog post, model card) that no scholarly
  index covers, but whose URL is live — check it by hand
- **ERROR** — every backend failed for this reference

## How verification works

For each reference, in order:

1. **Identifiers** — a cited DOI is resolved via Crossref and a cited arXiv id via the arXiv
   API. An identifier that resolves to a different title is flagged (copy-paste or
   hallucinated identifiers are a common form of citation corruption).
2. **Google Scholar** — quoted-title query, then a refined title + author + year query.
3. **Fallbacks** — if nothing plausible was found yet: arXiv title search, then Crossref
   bibliographic search. arXiv covers most ML papers, including ICLR/ICML papers that have
   no DOI. Preprint years may precede the cited (publication) year by up to 3 years.
4. **Web resources** — unresolved `@misc`-type entries with a `url` (or `\url{}` in
   `howpublished`) get a reachability check.
5. **Corroboration** — suggested corrections are cross-checked against Semantic Scholar.

Author matching compares last name + first initial, tolerates truncated author lists and
indexes that store names family-first.

## Setup

```bash
conda env create -f environment.yaml
conda activate cite-check
pip install -e ".[dev]"
```

## Usage

```bash
# Parse and list references without verifying
cite-check verify refs.bib --dry-run

# Full verification (free scholarly backend + arXiv/Crossref fallbacks)
cite-check verify refs.bib

# Reliable paid backend (https://serpapi.com, ~100 free searches/month)
export CITECHECK_SERPAPI_KEY=...
cite-check verify refs.bib --backend serpapi

# PDF input (heuristic parser, or GROBID if you run a server)
cite-check verify paper.pdf
cite-check verify paper.pdf --parser grobid

# Outputs
cite-check verify refs.bib --json results.json --report report.md --emit-fixed-bib

# Query cache (re-runs never re-hit the network)
cite-check cache path
cite-check cache clear
```

`--emit-fixed-bib` edits only the disputed fields of each MISMATCH entry (a wrong DOI is
dropped); all other fields of the original entry are kept.

Exit codes: `0` all verified (or web-only), `1` problems found (CI-friendly), `2` usage/input error.

### Configuration

Precedence: CLI flags > `CITECHECK_*` env vars (or `.env`) > `~/.config/cite-check/config.toml` > defaults.

| Key | Default | Meaning |
|---|---|---|
| `backend` | `scholarly` | `scholarly` (free scraper) or `serpapi` (paid, reliable) |
| `serpapi_key` | — | SerpAPI key for `--backend serpapi` |
| `scholar_only` | `false` | Disable all helpers: DOI/arXiv checks, arXiv/Crossref fallbacks, URL checks, Semantic Scholar corroboration |
| `cache_path` | `~/.cache/cite-check/cache.db` | SQLite query cache |
| `min_interval_s` | `3.0` | Polite delay between Scholar requests |
| `grobid_url` | `http://localhost:8070` | GROBID server for `--parser grobid` |

> **Note on Google Scholar:** there is no official API. The free `scholarly` backend scrapes
> Scholar, and Google often blocks it outright — a blocked scraper sees a redirect page that
> `scholarly` reports as *zero results*, not an error. cite-check therefore sends a canary
> query (`"Attention Is All You Need"`) first; if it returns nothing, Scholar is skipped with a
> warning and verification runs on arXiv + Crossref alone (with `--scholar-only` it aborts
> instead). Use the SerpAPI backend for real Scholar coverage.

## Development

```bash
pytest            # run tests (network-free; recorded/faked backend responses)
pytest -m live    # opt-in tests that hit real backends
ruff check . && ruff format --check .
mypy src
```

## Status

- [x] M1 — Skeleton + BibTeX ingestion (`--dry-run`)
- [x] M2 — Verification engine (backend protocol, cache, rate limiter, fuzzy matching)
- [x] M3 — Fix suggestions + JSON/Markdown reports + `--emit-fixed-bib`
- [x] M4 — PDF ingestion (heuristic references parser, DOI harvesting)
- [x] M5 — SerpAPI backend, Crossref/Semantic Scholar corroboration, GROBID client, config file
- [x] M6 — Scholar block detection, arXiv backend + fallbacks, DOI/arXiv identifier checks, `WEB_ONLY` status, field-preserving fixes
