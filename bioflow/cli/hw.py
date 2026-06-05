"""`bioflow hw` and `bioflow tools` — hardware introspection commands."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint

from bioflow.cli._app import REGISTRY_DEFAULT, app, console


@app.command("hw")
def hw_cmd() -> None:
    """Detect and print hardware profile (CPU / RAM / GPU / disk / arch)."""
    from bioflow.core.hardware import detect

    profile = detect()
    rprint(profile.model_dump())


@app.command("tools")
def tools_cmd(
    registry_dir: Path = typer.Option(
        REGISTRY_DEFAULT,
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
