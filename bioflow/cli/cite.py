"""`bioflow cite` — citations (with DOIs) for the tools a recipe or tool uses.

bioflow is plumbing; cite the underlying tools in your methods.  This prints a
ready-to-paste list (or BibTeX) for a whole recipe or specific tools.
"""
from __future__ import annotations

from typing import List

import typer
from rich import print as rprint

from bioflow.cli._app import app


@app.command("cite")
def cite_cmd(
    targets: List[str] = typer.Argument(
        ..., help="A recipe name (e.g. prokaryote_assembly) OR one or more tool "
                  "ids (e.g. spades prokka).",
    ),
    fmt: str = typer.Option(
        "text", "--format", "-f", help="Output format: text | bibtex.",
    ),
) -> None:
    """Print the citations + DOIs for the tools you used.

    \b
    Examples:
      bioflow cite prokaryote_assembly            # every tool the recipe runs
      bioflow cite spades prokka                  # specific tools
      bioflow cite prokaryote_assembly -f bibtex > refs.bib
    """
    from bioflow.core import citations  # noqa: PLC0415
    from bioflow.recipes import names as recipe_names  # noqa: PLC0415

    if fmt not in ("text", "bibtex"):
        rprint("[red]--format must be 'text' or 'bibtex'[/]")
        raise typer.Exit(code=2)

    unknown: List[str] = []
    if len(targets) == 1 and targets[0] in set(recipe_names()):
        entries = citations.citations_for_recipe(targets[0])
        header = f"Tools used by recipe '{targets[0]}' — please cite:"
    else:
        entries, unknown = citations.citations_for_tools(targets)
        header = "Please cite:"

    if unknown:
        rprint(f"[yellow]unknown tool id(s): {', '.join(unknown)} "
               f"(see: bioflow tools)[/]")
    if not entries:
        rprint("[red]no citations found for the given target(s).[/]")
        raise typer.Exit(code=1)

    if fmt == "bibtex":
        typer.echo(citations.format_bibtex(entries))
        return

    rprint(f"\n[bold]{header}[/]")
    typer.echo(citations.format_text(entries))
    n_missing = sum(1 for e in entries if not e.get("doi"))
    if n_missing:
        rprint(f"[dim]{n_missing} tool(s) have no MEDLINE DOI on record; "
               f"see docs/reference/tools.md for their reference.[/]")
