"""`bioflow provenance show` — render a recorded run's provenance."""
from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich import print as rprint

from bioflow.cli._app import app, console


@app.command("provenance")
def provenance_cmd(
    action: str = typer.Argument("show", help="show"),
    workspace: Path = typer.Argument(
        ..., exists=True, file_okay=False, dir_okay=True,
        help="Recipe workspace holding provenance.json.",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Emit the raw provenance.json document."),
) -> None:
    """Inspect the provenance a recipe run recorded into its workspace.

    \b
    A recipe run with provenance enabled (the default) writes:
      • provenance.json          — flat, per-stage run record
      • ro-crate-metadata.json   — RO-Crate 1.1 research object

    This reads provenance.json and prints a per-stage summary: image +
    pinned digest, exit code, and each input file's SHA-256.
    """
    import json  # noqa: PLC0415

    from bioflow.core.provenance import PROVENANCE_JSON  # noqa: PLC0415

    if action != "show":
        rprint(f"[red]Unknown action {action!r}.[/]  Use: show")
        raise typer.Exit(code=1)

    path = workspace / PROVENANCE_JSON
    if not path.exists():
        rprint(
            f"[yellow]no {PROVENANCE_JSON} in {workspace}[/] — run a recipe "
            "with provenance enabled (the default) first."
        )
        raise typer.Exit(code=0)

    doc = json.loads(path.read_text(encoding="utf-8"))

    if json_out:
        sys.stdout.write(json.dumps(doc, indent=2) + "\n")
        return

    console.print(
        f"\n[bold]Provenance:[/] [cyan]{doc.get('pipeline','?')}[/]  "
        f"[dim](bioflow {doc.get('bioflow_version','?')})[/]"
    )
    console.print(
        f"[dim]  {doc.get('started_at','?')} → {doc.get('ended_at','?')}[/]\n"
    )

    for i, s in enumerate(doc.get("stages", [])):
        status = "[green]ok[/]" if s.get("exit_code") == 0 else "[red]fail[/]"
        cached = " [dim](cached)[/]" if s.get("cached") else ""
        digest = s.get("image_digest")
        dig_str = f"  [dim]@{digest[:19]}…[/]" if digest else "  [yellow](unpinned)[/]"
        console.print(f"  [bold]#{i} {s.get('name')}[/]  {status}{cached}")
        console.print(f"      [dim]{s.get('image')}[/]{dig_str}")
        for f in s.get("inputs", []):
            sha = (f.get("sha256") or "")[:16]
            console.print(
                f"      [dim]in:[/] {Path(f['path']).name}  "
                f"[dim]sha256={sha}…[/]"
            )

    n = len(doc.get("stages", []))
    n_pinned = sum(1 for s in doc.get("stages", []) if s.get("image_digest"))
    console.print(
        f"\n[dim]{n} stages · {n_pinned} with pinned digest · "
        f"see ro-crate-metadata.json for the RO-Crate object[/]"
    )
