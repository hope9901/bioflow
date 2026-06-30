"""`bioflow overview` — tidy results + an at-a-glance overview from a finished run.

EXPERIMENTAL: harvests a completed workspace (single `recipe run` or a
`cohort`) into Layer-1 tidy data + a Layer-2 overview.html.  Only
`prokaryote_assembly` has a harvester so far.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint

from bioflow.cli._app import app


@app.command("overview")
def overview_cmd(
    recipe: str = typer.Argument(..., help="Recipe that produced the workspace."),
    workspace: Path = typer.Argument(..., help="Finished run / cohort output dir."),
    out: Optional[Path] = typer.Option(
        None, "--out", "-o",
        help="Where to write results/ (default: <workspace>/results).",
    ),
) -> None:
    """Harvest tidy per-sample metrics + a self-contained overview report.

    \b
    Example:
      bioflow overview prokaryote_assembly ./out
      # writes out/results/{assembly_metrics.csv, results.json, overview.html}

    Layer 1 (assembly_metrics.csv + results.json) is tidy data to plot
    yourself; Layer 2 (overview.html) is the canonical at-a-glance view.
    """
    from bioflow.core.results import build_overview  # noqa: PLC0415

    try:
        res = build_overview(recipe, workspace, out)
    except ValueError as exc:
        rprint(f"[red]{exc}[/]")
        raise typer.Exit(code=1)

    rprint(f"\n[green]✓ {len(res['rows'])} sample(s) harvested.[/]")
    rprint(f"[dim]  tidy data → {res['csv']}[/]")
    rprint(f"[dim]  manifest  → {res['manifest']}[/]")
    rprint(f"[dim]  overview  → {res['overview']}[/]")
