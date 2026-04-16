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
) -> None:
    """List tools available on this host, classified by hardware compatibility."""
    from bioflow.core.compatibility import classify
    from bioflow.core.hardware import detect
    from bioflow.core.registry import load_registry

    hw = detect()
    tools = load_registry(registry_dir)
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
) -> None:
    """Run a preset (recommended) pipeline against an input config."""
    from bioflow.core.planner import plan_from_preset
    from bioflow.core.runner import run_plan

    execution_plan = plan_from_preset(preset, config)
    run_plan(execution_plan)


@app.command("custom")
def custom_cmd(
    pipeline: str = typer.Option(..., "--pipeline", help="genome_assembly | rnaseq_deg"),
    out: Path = typer.Option(Path("custom_config.yaml"), "--out", "-o"),
) -> None:
    """Interactively pick tools per stage (only hardware-compatible ones shown)."""
    from bioflow.core.planner import interactive_build

    interactive_build(pipeline, out)
    rprint(f"[green]Saved custom pipeline config to[/] {out}")


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
    name: Optional[str] = typer.Argument(None),
) -> None:
    """Fetch or verify reference databases (Pfam/Dfam/UniProt/eggNOG/KEGG/...)."""
    raise typer.Exit(code=1)  # TODO: implement in step 2+


@app.command("update")
def update_cmd(
    action: str = typer.Argument("run", help="run | status | approve"),
) -> None:
    """Run the monthly Deep Research registry-update workflow (semi-automated)."""
    raise typer.Exit(code=1)  # TODO: implement in step 10


if __name__ == "__main__":
    app()
