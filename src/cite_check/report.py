"""Report outputs: rich terminal table, JSON, Markdown, fixed .bib (plan §4.5)."""

import json
from collections import Counter

from jinja2 import Template
from rich.console import Console
from rich.table import Table

from cite_check.models import VerificationResult, VerificationStatus

_STATUS_STYLE = {
    VerificationStatus.VERIFIED: "green",
    VerificationStatus.MISMATCH: "yellow",
    VerificationStatus.NOT_FOUND: "red",
    VerificationStatus.ERROR: "magenta",
}


def summarize(results: list[VerificationResult]) -> Counter[VerificationStatus]:
    return Counter(r.status for r in results)


def print_report(results: list[VerificationResult], console: Console) -> None:
    counts = summarize(results)
    summary = ", ".join(
        f"{counts[status]} {status.value.lower().replace('_', ' ')}"
        for status in VerificationStatus
        if counts[status]
    )
    console.print(f"\n[bold]{len(results)} references:[/bold] {summary}\n")

    table = Table()
    table.add_column("status")
    table.add_column("key", style="cyan", no_wrap=True)
    table.add_column("title", max_width=50)
    table.add_column("score", justify="right")
    table.add_column("issue", max_width=50)
    for result in results:
        issue = "; ".join(
            f"{field}: {cited!r} vs {found!r}"
            for field, (cited, found) in result.field_diffs.items()
        )
        if result.note:
            issue = f"{issue}; {result.note}" if issue else result.note
        table.add_row(
            f"[{_STATUS_STYLE[result.status]}]{result.status.value}[/]",
            result.reference.key or "-",
            result.reference.title,
            f"{result.score:.0f}" if result.best_match else "-",
            issue or "-",
        )
    console.print(table)


def to_json(results: list[VerificationResult]) -> str:
    return json.dumps([r.model_dump(mode="json") for r in results], indent=2, ensure_ascii=False)


_MARKDOWN_TEMPLATE = Template(
    """\
# cite-check report

**{{ results | length }} references** — {{ summary }}

{% for r in problems %}
## {{ r.status.value }}: {{ r.reference.key or r.reference.title }}

- **Cited:** {{ r.reference.title }}{% if r.reference.year %} ({{ r.reference.year }}){% endif %}
{%- if r.best_match %}
- **Found:** {{ r.best_match.title }}
  {%- if r.best_match.year %} ({{ r.best_match.year }}){% endif %}
  {%- if r.best_match.url %} — {{ r.best_match.url }}{% endif %}
{%- endif %}
{%- for field, diff in r.field_diffs.items() %}
- **{{ field }}:** cited `{{ diff[0] }}` — scholar says `{{ diff[1] }}`
{%- endfor %}
{%- if r.note %}
- _{{ r.note }}_
{%- endif %}
{%- if r.suggested_fix and r.suggested_fix.corrected_bibtex %}

Suggested fix:

```bibtex
{{ r.suggested_fix.corrected_bibtex }}
```
{%- endif %}
{% endfor %}
{%- if not problems %}
All citations verified. ✓
{%- endif %}
"""
)


def to_markdown(results: list[VerificationResult]) -> str:
    counts = summarize(results)
    summary = ", ".join(
        f"{counts[status]} {status.value}" for status in VerificationStatus if counts[status]
    )
    problems = [r for r in results if r.status != VerificationStatus.VERIFIED]
    return str(_MARKDOWN_TEMPLATE.render(results=results, problems=problems, summary=summary))


def build_fixed_bib(results: list[VerificationResult]) -> str:
    """Original entries, with corrected versions substituted where a fix exists."""
    blocks = []
    for result in results:
        if result.reference.source != "bibtex":
            continue
        fix = result.suggested_fix
        if fix is not None and fix.corrected_bibtex:
            blocks.append(fix.corrected_bibtex)
        else:
            blocks.append(result.reference.raw.strip())
    return "\n\n".join(blocks) + "\n"
