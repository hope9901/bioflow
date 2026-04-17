"""bioflow CLI entry point.

Subcommands (MVP scope):
  bioflow hw            Show detected hardware profile.
  bioflow tools         List tools available on this host (filtered by hw).
  bioflow recommend     Run a preset pipeline.
  bioflow custom        Interactively build a pipeline from compatible tools.
  bioflow run           Execute a pipeline config file.
  bioflow db            Fetch / manage reference databases.
  bioflow update        Run the monthly registry update workflow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="bioflow: genome assembly/annotation & RNA-seq DEG pipeline platform.",
)
console = Console()


@app.command("hw")
def hw_cmd() -> None:
    """Detect and print hardware profile (CPU / RAM / GPU / disk / arch)."""
    from bioflow.core.hardware import detect

    profile = detect()
    rprint(profile.model_dump())


@app.command("tools")
def tools_cmd(
    registry_dir: Path = typer.Option(
        Path("registry"),
        "--registry",
        "-r",
        help="Path to tool registry directory.",
    ),
    category: Optional[str] = typer.Option(None, "--category", "-c"),
    recommend: Optional[str] = typer.Option(
        None, "--recommend",
        help="Score and rank presets for this pipeline on the current host "
             "(genome_assembly | rnaseq_deg).",
    ),
) -> None:
    """List tools available on this host, classified by hardware compatibility."""
    from bioflow.core.compatibility import classify, recommend_presets
    from bioflow.core.hardware import detect
    from bioflow.core.registry import load_registry

    hw = detect()
    tools = load_registry(registry_dir)

    if recommend:
        recs = recommend_presets(tools, hw, recommend, registry_dir=registry_dir)
        if not recs:
            console.print(f"[yellow]No presets found for pipeline '{recommend}'[/]")
            return
        console.print(f"\n[bold]Preset recommendations for [cyan]{recommend}[/] on this host:[/]\n")
        for r in recs:
            runnable_tag = "[green]✓ runnable[/]" if r["runnable"] else "[red]✗ incompatible tools[/]"
            score_color = "green" if r["score"] >= 80 else "yellow" if r["score"] >= 50 else "red"
            console.print(
                f"  [{score_color}]{r['score']:3d}[/]  [bold]{r['preset']}[/]  {runnable_tag}"
            )
            if r["applies_to"]:
                at = r["applies_to"]
                console.print(
                    f"       species={at.get('species',[])}  "
                    f"read_type={at.get('read_type',[])}  "
                    f"mode={at.get('mode',[])}"
                )
            if r["incompatible_tools"]:
                console.print(
                    f"       [red]incompatible:[/] {', '.join(r['incompatible_tools'])}"
                )
            if r["slow_tools"]:
                console.print(
                    f"       [yellow]slow:[/] {', '.join(r['slow_tools'])}"
                )
        return

    if category:
        tools = [t for t in tools if t.category == category]
    classified = classify(tools, hw)
    for status, bucket in classified.items():
        color = {"installable": "green", "runnable_slow": "yellow", "incompatible": "red"}[status]
        console.print(f"\n[bold {color}]{status}[/] ({len(bucket)} tools)")
        for t in bucket:
            console.print(f"  - {t.id}  [{t.category}]  image={t.container.image}")


@app.command("recommend")
def recommend_cmd(
    preset: str = typer.Option(..., "--preset", "-p"),
    config: Path = typer.Option(..., "--config", "-c", exists=True),
    registry: Path = typer.Option(Path("registry"), "--registry", "-r"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plan without executing."),
) -> None:
    """Run a preset (recommended) pipeline against an input config."""
    import yaml  # noqa: PLC0415

    from bioflow.core.compatibility import classify  # noqa: PLC0415
    from bioflow.core.hardware import detect  # noqa: PLC0415
    from bioflow.core.planner import plan_from_preset  # noqa: PLC0415
    from bioflow.core.registry import load_registry  # noqa: PLC0415
    from bioflow.core.runner import run_plan  # noqa: PLC0415

    # Resolve registry_dir from config file (may override --registry)
    with config.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    reg_dir = Path(raw.get("registry_dir", str(registry)))

    # Hardware + compatibility summary
    hw = detect()
    tools = load_registry(reg_dir)
    classified = classify(tools, hw)
    slow = classified["runnable_slow"]
    bad  = classified["incompatible"]
    if bad:
        console.print(
            f"[red]⚠  {len(bad)} tool(s) incompatible with this host:[/] "
            + ", ".join(t.id for t in bad)
        )
    if slow:
        console.print(
            f"[yellow]⚡ {len(slow)} tool(s) may run slowly on this host:[/] "
            + ", ".join(t.id for t in slow)
        )

    execution_plan = plan_from_preset(preset, config)

    if dry_run:
        console.print("\n[bold]Execution plan (dry-run):[/]")
        for s in execution_plan.stages:
            console.print(f"  {s.stage_id}  →  [cyan]{s.tool_id}[/]")
        return

    run_plan(execution_plan)


@app.command("custom")
def custom_cmd(
    pipeline: str = typer.Option(..., "--pipeline", help="genome_assembly | rnaseq_deg"),
    out: Path = typer.Option(Path("custom_config.yaml"), "--out", "-o"),
    registry: Path = typer.Option(Path("registry"), "--registry", "-r"),
) -> None:
    """Interactively pick tools per stage (only hardware-compatible ones shown)."""
    from bioflow.core.planner import interactive_build  # noqa: PLC0415

    interactive_build(pipeline, out, registry_dir=registry)
    rprint(f"[green]✓ Saved custom pipeline config →[/] {out}")


@app.command("run")
def run_cmd(config: Path = typer.Argument(..., exists=True)) -> None:
    """Execute a saved pipeline config file."""
    from bioflow.core.planner import plan_from_config
    from bioflow.core.runner import run_plan

    execution_plan = plan_from_config(config)
    run_plan(execution_plan)


@app.command("db")
def db_cmd(
    action: str = typer.Argument(..., help="fetch | list | verify"),
    name: Optional[str] = typer.Argument(None, help="Database key (see 'bioflow db list')."),
    dest: Path = typer.Option(
        Path("data/references"),
        "--dest", "-d",
        help="Root directory for downloaded databases.",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Re-download even if file exists."),
) -> None:
    """Fetch or verify reference databases (eggNOG / Pfam / Dfam / BUSCO / UniProt)."""
    from bioflow.core.db import fetch_db, list_dbs, verify_db  # noqa: PLC0415

    if action == "list":
        rows = list_dbs()
        console.print("\n[bold]Available reference databases:[/]\n")
        for r in rows:
            used = ", ".join(r["used_by"])
            console.print(
                f"  [cyan]{r['key']:<20}[/]  {r['size_gb']:5.1f} GB  "
                f"used by: {used}"
            )
            console.print(f"    {r['name']}")
            if r["notes"]:
                console.print(f"    [dim]{r['notes']}[/]")
        return

    if not name:
        rprint("[red]Error:[/] 'name' argument required for fetch/verify.")
        raise typer.Exit(code=1)

    if action == "fetch":
        try:
            path = fetch_db(name, dest, skip_if_exists=not force)
            rprint(f"[green]✓[/] {name} → {path}")
        except (KeyError, RuntimeError) as exc:
            rprint(f"[red]Error:[/] {exc}")
            raise typer.Exit(code=1) from exc

    elif action == "verify":
        try:
            ok = verify_db(name, dest)
            if ok:
                rprint(f"[green]✓[/] {name} — OK")
            else:
                rprint(f"[red]✗[/] {name} — FAILED or missing")
                raise typer.Exit(code=1)
        except KeyError as exc:
            rprint(f"[red]Error:[/] {exc}")
            raise typer.Exit(code=1) from exc

    else:
        rprint(f"[red]Unknown action '{action}'.[/] Use: fetch | list | verify")
        raise typer.Exit(code=1)


@app.command("update")
def update_cmd(
    action: str = typer.Argument(..., help="approve"),
    candidate: Optional[Path] = typer.Option(
        None, "--candidate", "-c",
        help="Path to a single candidate YAML to approve.",
    ),
    candidates_dir: Optional[Path] = typer.Option(
        None, "--candidates-dir",
        help="Approve every .yaml in this directory.",
    ),
    registry_dir: Path = typer.Option(
        Path("registry"), "--registry",
        help="Root of the tool registry.",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing entries."),
    delete_candidate: bool = typer.Option(
        False, "--delete-candidate",
        help="Delete candidate file(s) after successful approval.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without writing."),
) -> None:
    """Registry update utilities.

    \b
    approve   Promote a candidate YAML (or a whole directory) to the registry.
    """
    from bioflow.core.approve import (  # noqa: PLC0415
        ApprovalError,
        approve_all_candidates,
        approve_candidate,
    )

    if action == "approve":
        if candidate and candidates_dir:
            rprint("[red]Specify --candidate OR --candidates-dir, not both.[/]")
            raise typer.Exit(code=1)

        if candidate:
            if dry_run:
                rprint(f"[dim][DRY RUN] Would approve {candidate}[/]")
            try:
                dest = approve_candidate(
                    candidate,
                    registry_dir=registry_dir,
                    overwrite=overwrite,
                    delete_candidate=delete_candidate,
                    dry_run=dry_run,
                )
                if not dry_run:
                    rprint(f"[green]✓ Approved:[/] {candidate.name} → [cyan]{dest}[/]")
                else:
                    rprint(f"[dim]Would write → {dest}[/]")
            except ApprovalError as exc:
                rprint(f"[red]Approval failed:[/] {exc}")
                raise typer.Exit(code=1)

        elif candidates_dir:
            if not candidates_dir.is_dir():
                rprint(f"[red]Not a directory:[/] {candidates_dir}")
                raise typer.Exit(code=1)
            results = approve_all_candidates(
                candidates_dir,
                registry_dir=registry_dir,
                overwrite=overwrite,
                delete_candidates=delete_candidate,
                dry_run=dry_run,
            )
            if not results:
                rprint("[yellow]No candidate YAML files found.[/]")
                raise typer.Exit(code=0)

            approved = [r for r in results if r["status"] == "approved"]
            skipped  = [r for r in results if r["status"] == "skipped"]
            errors   = [r for r in results if r["status"] == "error"]

            for r in approved:
                rprint(f"[green]✓ approved[/]  {r['file']} → {r.get('dest','')}")
            for r in skipped:
                rprint(f"[yellow]⚠ skipped[/]   {r['file']}: {r.get('error','')}")
            for r in errors:
                rprint(f"[red]✗ error[/]     {r['file']}: {r.get('error','')}")

            rprint(
                f"\n[bold]Total:[/] {len(results)}  "
                f"[green]approved={len(approved)}[/]  "
                f"[yellow]skipped={len(skipped)}[/]  "
                f"[red]errors={len(errors)}[/]"
            )
            if errors:
                raise typer.Exit(code=1)
        else:
            rprint("[red]--candidate or --candidates-dir is required for 'approve'.[/]")
            raise typer.Exit(code=1)

    else:
        rprint(f"[red]Unknown action '{action}'.[/] Available: approve")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
