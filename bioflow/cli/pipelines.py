"""`bioflow recommend / custom / run / status` — pipeline execution + state."""
from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich import print as rprint

from bioflow.cli._app import REGISTRY_DEFAULT, app, console


@app.command("recommend")
def recommend_cmd(
    preset: str = typer.Option(..., "--preset", "-p"),
    config: Path = typer.Option(..., "--config", "-c", exists=True),
    registry: Path = typer.Option(REGISTRY_DEFAULT, "--registry", "-r"),
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
    registry: Path = typer.Option(REGISTRY_DEFAULT, "--registry", "-r"),
) -> None:
    """Interactively pick tools per stage (only hardware-compatible ones shown)."""
    from bioflow.core.planner import interactive_build  # noqa: PLC0415

    interactive_build(pipeline, out, registry_dir=registry)
    rprint(f"[green]✓ Saved custom pipeline config →[/] {out}")


@app.command("run")
def run_cmd(
    config: Path = typer.Argument(..., exists=True),
    fresh: bool = typer.Option(
        False, "--fresh",
        help="Delete the workspace's checkpoint and re-run every stage from "
             "scratch.  By default a re-invoked `bioflow run` resumes from "
             "the last completed stage.",
    ),
    resume: bool = typer.Option(
        False, "--resume",
        help="Explicit alias for the default behaviour — skip stages already "
             "marked completed in `.bioflow_state.json` and continue from the "
             "first incomplete one.  Mutually exclusive with --fresh.",
    ),
) -> None:
    """Execute a saved pipeline config file.

    \b
    Resume semantics:
      • Default                — implicit resume (skip checkpointed stages)
      • --resume               — explicit form of the default
      • --fresh                — wipe `.bioflow_state.json` and run all stages
    """
    if fresh and resume:
        rprint("[red]--fresh and --resume are mutually exclusive.[/]")
        raise typer.Exit(code=2)

    from bioflow.core.checkpoint import STATE_FILE  # noqa: PLC0415
    from bioflow.core.planner import plan_from_config  # noqa: PLC0415
    from bioflow.core.runner import run_plan  # noqa: PLC0415

    execution_plan = plan_from_config(config)

    if fresh:
        state_path = Path(execution_plan.workdir) / STATE_FILE
        if state_path.exists():
            state_path.unlink()
            rprint(f"[yellow]✗ removed[/] {state_path}  [dim](--fresh)[/]")
        else:
            rprint(f"[dim]no checkpoint to remove ({state_path})[/]")

    run_plan(execution_plan)


@app.command("status")
def status_cmd(
    workdir: Path = typer.Argument(
        ..., exists=True, file_okay=False, dir_okay=True,
        help="Workspace directory holding `.bioflow_state.json`.",
    ),
    json_out: bool = typer.Option(
        False, "--json",
        help="Emit the raw state document as JSON.",
    ),
) -> None:
    """Show resume state for a previously-run workspace.

    \b
    Reads `<workdir>/.bioflow_state.json` and reports:
      • completed_stages — what `--resume` will skip
      • failed_stages    — last error per stage, with stderr tail
      • artifacts        — recorded stage_dir for each completed stage
    """
    from bioflow.core.checkpoint import STATE_FILE, load  # noqa: PLC0415

    state_path = workdir / STATE_FILE
    if not state_path.exists():
        rprint(
            f"[yellow]no checkpoint at {state_path}[/] — this workspace has "
            "not been run yet, or `--fresh` cleared it."
        )
        raise typer.Exit(code=0)

    state = load(workdir)

    if json_out:
        import json  # noqa: PLC0415
        sys.stdout.write(json.dumps(state, indent=2, sort_keys=True) + "\n")
        return

    completed = state.get("completed_stages", [])
    failed = state.get("failed_stages", {})
    artifacts = state.get("artifacts", {})

    console.print(f"\n[bold]Checkpoint:[/] [dim]{state_path}[/]\n")
    console.print(f"[bold green]completed_stages[/] ({len(completed)})")
    for s in completed:
        console.print(f"  [green]✓[/] {s}  → [dim]{artifacts.get(s, {}).get('stage_dir', '?')}[/]")

    if failed:
        console.print(f"\n[bold red]failed_stages[/] ({len(failed)})")
        for sid, info in failed.items():
            err = info.get("error", "?")
            console.print(f"  [red]✗[/] {sid}  [dim]{err}[/]")
            tail = (info.get("stderr_tail") or "").strip()
            if tail:
                # Indent each line of the stderr tail.
                for line in tail.splitlines()[-5:]:
                    console.print(f"      [dim]│ {line}[/]")
    else:
        console.print("\n[dim]no failed stages recorded[/]")

    next_stage = "—"
    # Pick the first stage not yet completed; we don't know the full plan
    # here, so we surface this only as a hint.
    if failed:
        next_stage = sorted(failed.keys())[0]
    console.print(
        f"\n[dim]Resume would re-run from:[/] [cyan]{next_stage}[/]  "
        f"(use `bioflow run <config>` to continue, or add `--fresh` to start over)"
    )
