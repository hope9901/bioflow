"""`bioflow doctor` — 12-point host self-check."""
from __future__ import annotations

import sys
from pathlib import Path

import typer

from bioflow.cli._app import REGISTRY_DEFAULT, app, console


@app.command("doctor")
def doctor_cmd(
    workspace: Path = typer.Option(
        Path.cwd(),
        "--workspace", "-w",
        help="Directory used to test disk space and write permissions.",
    ),
    registry: Path = typer.Option(
        REGISTRY_DEFAULT,
        "--registry", "-r",
        help="Tool registry to validate (defaults to ./registry or the bundled copy).",
    ),
    json_out: bool = typer.Option(
        False, "--json",
        help="Emit machine-readable JSON instead of the human report.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Include per-check detail blocks in the human report.",
    ),
) -> None:
    """Self-check this host before running a recipe.

    \b
    Checks (each is independent and never raises):
      python / arch / docker_cli / docker_daemon / docker_socket
      cpu / ram / disk / gpu / registry / home_config / workspace

    \b
    Exit code: 1 if any check FAILs, 0 otherwise (warnings do not block).
    Use --json in CI to consume the structured report.
    """
    from bioflow.core.doctor import (  # noqa: PLC0415
        exit_code,
        run_checks,
        summarize,
    )

    results = run_checks(workspace=workspace, registry_dir=registry)

    if json_out:
        import json  # noqa: PLC0415

        payload = {
            "summary": summarize(results),
            "checks": [r.to_dict() for r in results],
        }
        # bypass rich so output is clean JSON
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        raise typer.Exit(code=exit_code(results))

    _glyph = {"ok": "[green]OK  [/]", "warn": "[yellow]WARN[/]", "fail": "[red]FAIL[/]"}
    console.print("\n[bold]bioflow doctor[/]\n")
    for r in results:
        console.print(f"  {_glyph[r.status]}  [bold]{r.name:<14}[/]  {r.message}")
        if r.fix and r.status != "ok":
            console.print(f"        [dim]→ {r.fix}[/]")
        if verbose and r.detail:
            for k, v in r.detail.items():
                console.print(f"        [dim]{k}={v}[/]")

    s = summarize(results)
    total = sum(s.values())
    console.print(
        f"\n[bold]{total} checks[/] · "
        f"[green]{s['ok']} ok[/] · "
        f"[yellow]{s['warn']} warn[/] · "
        f"[red]{s['fail']} fail[/]"
    )
    raise typer.Exit(code=exit_code(results))


