"""`bioflow cohort` — run a single-sample recipe across a samplesheet."""
from __future__ import annotations

from pathlib import Path

import typer
from rich import print as rprint

from bioflow.cli._app import app, console
from bioflow.cli.recipe import _parse_recipe_extra


@app.command(
    "cohort",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cohort_cmd(
    ctx: typer.Context,
    recipe: str = typer.Argument(
        ..., help="Recipe to run once per sample (single-sample recipes only)."
    ),
    samplesheet: Path = typer.Option(
        ..., "--samplesheet", "-s",
        help="CSV with a sample-id column + per-sample param columns.",
    ),
    out: Path = typer.Option(
        Path("bioflow_cohort"), "--out", "-o",
        help="Cohort output dir; each sample lands in <out>/<sample_id>.",
    ),
    jobs: int = typer.Option(
        1, "--jobs", "-j", min=1,
        help="How many samples to run concurrently.",
    ),
    aggregate: bool = typer.Option(
        True, "--aggregate/--no-aggregate",
        help="Run MultiQC across all samples after they finish.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the per-sample plan without running.",
    ),
) -> None:
    """Fan a single-sample recipe across every row of a samplesheet.

    \b
    Example:
      bioflow cohort prokaryote_assembly -s samples.csv -o out -j 4
      # samples.csv:
      #   sample_id,r1,r2
      #   iso1,/data/iso1_R1.fq.gz,/data/iso1_R2.fq.gz
      #   iso2,/data/iso2_R1.fq.gz,/data/iso2_R2.fq.gz

    Shared options pass straight through to every sample, e.g.
    ``--reference ref.fa``.  Recipes that already loop over a samplesheet
    internally (rnaseq_deg, joint_genotyping) are NOT cohort targets.
    """
    from bioflow.core.cohort import read_samplesheet, run_cohort  # noqa: PLC0415

    # Shared --key value tokens apply to every sample.
    common = {k: str(v) for k, v in _parse_recipe_extra(ctx.args).items()}

    try:
        rows = read_samplesheet(samplesheet)
    except (ValueError, OSError) as exc:
        rprint(f"[red]{exc}[/]")
        raise typer.Exit(code=1)

    if dry_run:
        console.print(
            f"\n[bold]Cohort dry-run[/] — recipe [cyan]{recipe}[/], "
            f"{len(rows)} sample(s):\n"
        )
        for r in rows:
            params = {**common, **{k: v for k, v in r.items() if k != "sample_id"}}
            flags = " ".join(f"--{k.replace('_', '-')} {v}" for k, v in params.items())
            console.print(
                f"  [cyan]{r['sample_id']:<16}[/] -> {out}/{r['sample_id']}"
                f"   [dim]{flags}[/]"
            )
        return

    out = out.resolve()
    rprint(
        f"\n[bold]Cohort[/] [cyan]{recipe}[/] — {len(rows)} sample(s), "
        f"jobs={jobs}, workspace=[dim]{out}[/]"
    )
    report = run_cohort(
        recipe, samplesheet, out, common=common, jobs=jobs, aggregate=aggregate
    )

    console.print()
    for res in report.results:
        mark = "[green]✓[/]" if res.ok else "[red]✗[/]"
        detail = "" if res.ok else f"  [red]{res.error}[/]"
        console.print(f"  {mark} [cyan]{res.sample_id:<16}[/] {res.workspace}{detail}")
    console.print(
        f"\n[bold]{report.n_ok} ok[/], [bold]{report.n_failed} failed[/] "
        f"of {len(report.results)}."
    )
    if report.multiqc_report:
        rprint(f"[dim]cohort MultiQC → {report.multiqc_report}[/]")
    if report.n_failed:
        raise typer.Exit(code=1)
