"""cite-check CLI (plan §4.6).

Exit codes: 0 = all verified, 1 = problems found, 2 = usage/input error.
"""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import track
from rich.table import Table

from cite_check.backends import (
    CachedBackend,
    CrossrefBackend,
    ScholarBackend,
    ScholarlyBackend,
    SemanticScholarBackend,
    SerpApiBackend,
)
from cite_check.cache import QueryCache
from cite_check.config import Settings, load_settings
from cite_check.engine import VerificationEngine
from cite_check.ingest import parse_bibtex, parse_pdf
from cite_check.ingest.grobid import GrobidClient
from cite_check.models import Reference, VerificationStatus
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
            return GrobidClient(settings.grobid_url).parse_references(path)
        return parse_pdf(path)
    raise typer.BadParameter(f"Unsupported input type: {suffix} (expected .bib or .pdf)")


def _build_backend(settings: Settings, cache: QueryCache) -> ScholarBackend:
    limiter = RateLimiter(settings.min_interval_s)
    if settings.backend == "serpapi":
        inner: ScholarBackend = SerpApiBackend(settings.serpapi_key or "", limiter)
    elif settings.backend == "scholarly":
        inner = ScholarlyBackend(limiter)
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
        bool, typer.Option("--scholar-only", help="Disable Crossref/Semantic Scholar helpers.")
    ] = False,
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
    settings = load_settings(backend=backend, scholar_only=scholar_only or None)

    refs = dedupe_references(_ingest(input_file, parser, settings))
    if not refs:
        console.print("[red]No references found in input.[/red]")
        raise typer.Exit(code=2)

    _print_references(refs)
    if dry_run:
        return

    cache = QueryCache(settings.cache_path)
    engine = VerificationEngine(
        backend=_build_backend(settings, cache),
        crossref=None if settings.scholar_only else CrossrefBackend(RateLimiter(1.0)),
        corroborator=None if settings.scholar_only else SemanticScholarBackend(RateLimiter(1.0)),
        results_per_query=settings.results_per_query,
    )
    results = [
        engine.verify_one(ref) for ref in track(refs, description="Verifying", console=console)
    ]
    cache.close()

    print_report(results, console)

    if json_out is not None:
        json_out.write_text(to_json(results))
        console.print(f"JSON results written to [cyan]{json_out}[/cyan]")
    if report_out is not None:
        report_out.write_text(to_markdown(results))
        console.print(f"Markdown report written to [cyan]{report_out}[/cyan]")
    if emit_fixed_bib:
        fixed_path = input_file.with_suffix(".fixed.bib")
        fixed_path.write_text(build_fixed_bib(results))
        console.print(f"Corrected bibliography written to [cyan]{fixed_path}[/cyan]")

    if any(r.status != VerificationStatus.VERIFIED for r in results):
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
