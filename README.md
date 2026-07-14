# cite-check

Verify the citations of a written paper — input a **PDF** or a **BibTeX** file — against **Google Scholar**, and get a suggested fix for every incorrect or unverifiable reference.

Each reference is classified as:

- **VERIFIED** — a Scholar record matches (title, authors, year, venue consistent)
- **MISMATCH** — a close record exists but fields disagree; a corrected entry is suggested
- **NOT_FOUND** — no plausible record exists (possibly fabricated)

See [PLAN.md](PLAN.md) for the full project plan.

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

# Full verification (free scholarly backend; slow + politely rate-limited)
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

Exit codes: `0` all verified, `1` problems found (CI-friendly), `2` usage/input error.

### Configuration

Precedence: CLI flags > `CITECHECK_*` env vars (or `.env`) > `~/.config/cite-check/config.toml` > defaults.

| Key | Default | Meaning |
|---|---|---|
| `backend` | `scholarly` | `scholarly` (free scraper) or `serpapi` (paid, reliable) |
| `serpapi_key` | — | SerpAPI key for `--backend serpapi` |
| `scholar_only` | `false` | Disable Crossref DOI resolution + Semantic Scholar corroboration |
| `cache_path` | `~/.cache/cite-check/cache.db` | SQLite query cache |
| `min_interval_s` | `3.0` | Polite delay between Scholar requests |
| `grobid_url` | `http://localhost:8070` | GROBID server for `--parser grobid` |

> **Note on Google Scholar:** there is no official API. The free `scholarly` backend scrapes
> Scholar and will get rate-limited or blocked under load — keep volumes small, keep the
> default delay, or use the SerpAPI backend for anything serious.

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
