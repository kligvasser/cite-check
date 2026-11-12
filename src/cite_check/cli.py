"""cite-check CLI (plan §4.6).

Exit codes: 0 = all verified, 1 = problems found, 2 = usage/input error.
"""

from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.progress import track
from rich.table import Table

from cite_check.backends import (
    ArxivBackend,
    CachedBackend,
    CrossrefBackend,
    ScholarBackend,
    ScholarlyBackend,
    SemanticScholarBackend,
    SerpApiBackend,
)
from cite_check.backends.web import url_status
from cite_check.cache import QueryCache
from cite_check.config import Settings, load_settings
from cite_check.engine import VerificationEngine
from cite_check.ingest import parse_bibtex, parse_pdf
from cite_check.ingest.grobid import GrobidClient
from cite_check.models import PASSING_STATUSES, Reference
from cite_check.normalize import dedupe_references
from cite_check.ratelimit import RateLimiter
from cite_check.report import build_fixed_bib, print_report, to_json, to_markdown

app = typer.Typer(help="Verify paper citations against Google Scholar.", no_args_is_help=True)
cache_app = typer.Typer(help="Manage the query cache.")
app.add_typer(cache_app, name="cache")
console = Console()


@app.callback()
def _root() -> None:
    """Verify paper citations against Google Scholar."""


def _ingest(path: Path, parser: str, settings: Settings) -> list[Reference]:
    suffix = path.suffix.lower()
    if suffix == ".bib":
        return parse_bibtex(path)
    if suffix == ".pdf":
        if parser == "grobid":
            try:
                return GrobidClient(settings.grobid_url).parse_references(path)
            except httpx.HTTPError as exc:
                raise typer.BadParameter(
                    f"GROBID server not reachable at {settings.grobid_url} ({exc}). "
                    "Start one with: docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0"
                ) from exc
        try:
            return parse_pdf(path)
        except ValueError as exc:  # no references section found
            raise typer.BadParameter(str(exc)) from exc
    raise typer.BadParameter(f"Unsupported input type: {suffix} (expected .bib or .pdf)")


# a query Google Scholar always answers; zero hits means we are being blocked
CANARY_QUERY = '"Attention Is All You Need"'


def _scholar_is_answering(backend: ScholarBackend) -> bool:
    """The scholarly scraper reports a block page as *zero results*, not an error.

    Without this check every reference would silently become NOT_FOUND.
    """
    try:
        return bool(backend.search(CANARY_QUERY, 1))
    except Exception:
        return False


def _build_backend(settings: Settings, cache: QueryCache) -> ScholarBackend | None:
    limiter = RateLimiter(settings.min_interval_s)
    if settings.backend == "serpapi":
        inner: ScholarBackend = SerpApiBackend(settings.serpapi_key or "", limiter)
    elif settings.backend == "scholarly":
        inner = ScholarlyBackend(limiter)
        if not _scholar_is_answering(inner):  # uncached on purpose: tests *current* access
            if settings.scholar_only:
                raise typer.BadParameter(
                    "Google Scholar returned no results for a canary query — it is "
                    "blocking scripted access. Use --backend serpapi."
                )
            console.print(
                "[yellow]Google Scholar is blocking scripted access (canary query returned "
                "nothing). Falling back to arXiv + Crossref; use --backend serpapi for "
                "Scholar coverage.[/yellow]"
            )
            return None
    else:
        raise typer.BadParameter(f"Unknown backend: {settings.backend}")
    return CachedBackend(inner, cache)


def _print_references(refs: list[Reference]) -> None:
    table = Table(title=f"Parsed references ({len(refs)})")
    table.add_column("key", style="cyan", no_wrap=True)
    table.add_column("title", max_width=60)
    table.add_column("authors", max_width=40)
    table.add_column("year", justify="right")
    table.add_column("venue", max_width=30)
    for ref in refs:
        table.add_row(
            ref.key or "-",
            ref.title,
            "; ".join(ref.authors),
            str(ref.year) if ref.year else "-",
            ref.venue or "-",
        )
    console.print(table)


@app.command()
def verify(
    input_file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    backend: Annotated[
        str | None, typer.Option("--backend", help="scholarly (free) or serpapi (reliable).")
    ] = None,
    parser: Annotated[
        str, typer.Option("--parser", help="PDF parser: heuristic or grobid.")
    ] = "heuristic",
    scholar_only: Annotated[
        bool | None,
        typer.Option(
            "--scholar-only/--no-scholar-only",
            help="Disable (or re-enable) Crossref/Semantic Scholar helpers.",
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only parse and list references; skip verification.")
    ] = False,
    json_out: Annotated[
        Path | None, typer.Option("--json", help="Write full results as JSON.")
    ] = None,
    report_out: Annotated[
        Path | None, typer.Option("--report", help="Write a Markdown report.")
    ] = None,
    emit_fixed_bib: Annotated[
        bool,
        typer.Option("--emit-fixed-bib", help="Write <input>.fixed.bib with corrections applied."),
    ] = False,
) -> None:
    """Extract references from INPUT_FILE and verify each against Google Scholar."""
    settings = load_settings(backend=backend, scholar_only=scholar_only)

    parsed = _ingest(input_file, parser, settings)
    refs = dedupe_references(parsed)
    if not refs:
        console.print("[red]No references found in input.[/red]")
        raise typer.Exit(code=2)
    if len(refs) < len(parsed):
        console.print(
            f"[yellow]Skipped {len(parsed) - len(refs)} duplicate reference(s) "
            "(same title and year).[/yellow]"
        )

    _print_references(refs)
    if dry_run:
        return

    cache = QueryCache(settings.cache_path)
    helpers = not settings.scholar_only
    crossref = CrossrefBackend(RateLimiter(1.0)) if helpers else None
    arxiv = ArxivBackend(RateLimiter(3.0)) if helpers else None  # arXiv asks for 3 s
    fallbacks: list[ScholarBackend] = []
    if arxiv is not None and crossref is not None:
        fallbacks = [CachedBackend(arxiv, cache), CachedBackend(crossref, cache)]
    engine = VerificationEngine(
        backend=_build_backend(settings, cache),
        crossref=crossref,
        corroborator=SemanticScholarBackend(RateLimiter(1.0)) if helpers else None,
        results_per_query=settings.results_per_query,
        arxiv=arxiv,
        fallbacks=fallbacks,
        url_checker=url_status if helpers else None,
    )
    try:
        results = list(
            engine.verify_one_safe(ref)
            for ref in track(refs, description="Verifying", console=console)
        )
    finally:
        cache.close()

    print_report(results, console)

    if json_out is not None:
        json_out.write_text(to_json(results))
        console.print(f"JSON results written to [cyan]{json_out}[/cyan]")
    if report_out is not None:
        report_out.write_text(to_markdown(results))
        console.print(f"Markdown report written to [cyan]{report_out}[/cyan]")
    if emit_fixed_bib:
        if input_file.suffix.lower() != ".bib":
            console.print(
                "[yellow]--emit-fixed-bib only applies to BibTeX input; "
                "PDF references have no entries to rewrite.[/yellow]"
            )
        else:
            fixed_path = input_file.with_suffix(".fixed.bib")
            fixed_path.write_text(build_fixed_bib(results))
            console.print(f"Corrected bibliography written to [cyan]{fixed_path}[/cyan]")

    if any(r.status not in PASSING_STATUSES for r in results):
        raise typer.Exit(code=1)


@cache_app.command("clear")
def cache_clear() -> None:
    """Delete all cached query responses."""
    settings = load_settings()
    if not settings.cache_path.exists():
        console.print("Cache is already empty.")
        return
    cache = QueryCache(settings.cache_path)
    removed = cache.clear()
    cache.close()
    console.print(f"Removed {removed} cached queries.")


@cache_app.command("path")
def cache_path() -> None:
    """Print the cache file location."""
    console.print(str(load_settings().cache_path))


if __name__ == "__main__":
    app()
