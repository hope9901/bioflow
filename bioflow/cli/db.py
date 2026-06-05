"""`bioflow db` — fetch / list / verify reference databases."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint

from bioflow.cli._app import app, console


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
