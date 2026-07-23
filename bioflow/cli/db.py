"""`bioflow db` — fetch / list / verify reference databases."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint

from bioflow.cli._app import app, console


@app.command("db")
def db_cmd(
    action: str = typer.Argument(..., help="fetch | list | verify | manifest | status | update | provision | size | gc"),
    name: Optional[str] = typer.Argument(None, help="Database key (see 'bioflow db list')."),
    dest: Path = typer.Option(
        Path("data/references"),
        "--dest", "-d",
        help="Root directory for downloaded databases.",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Re-download even if file exists."),
    check_latest: bool = typer.Option(
        False, "--check-latest",
        help="[status] Probe upstream for the newest DB version (small HTTP request).",
    ),
    run: bool = typer.Option(
        False, "--run",
        help="[provision] Actually pull the tool image + build the DB "
             "(downloads GB). Default just prints the command.",
    ),
    no_update: bool = typer.Option(
        False, "--no-update",
        help="[ensure] Only flag a newer DB; don't auto-download it.",
    ),
) -> None:
    """Fetch / verify / list reference databases, or emit a refgenie manifest.

    \b
    list      Show every catalogued DB, its size, and which tools use it.
    fetch     Download a DB into --dest (resumable, size-checked).
    verify    Confirm a fetched DB is present (+ MD5 when registered).
    manifest  Emit a refgenie-compatible asset manifest (JSON) mapping
              genome/asset → catalogued DB, so labs on refgenie can see
              which existing assets satisfy a bioflow requirement.
    status    Installed vs catalog vs (with --check-latest) upstream version
              for a DB, or all annotation DBs. Shows update-available.
    update    Version-gated refresh: re-download only when upstream is newer.
    provision Build/download a DB *inside its tool's container* (the image
              ships the downloader). Prints the command; --run executes it.
    ensure    Run-time gate for a TOOL: check each DB's version and auto-update
              only the stale ones (--no-update to just flag).
    size      Show what each installed DB occupies under --dest, plus free
              space — the counterpart to provisioning them.
    gc        Delete an installed DB to reclaim its space (--force to skip the
              confirmation). Re-provision it any time.
    """
    import json  # noqa: PLC0415

    from bioflow.core.db import (  # noqa: PLC0415
        _DB_CATALOG, catalog_version, db_status, ensure_db_current, fetch_db,
        list_dbs, provision_command, refgenie_manifest, update_db, verify_db,
    )

    if action in ("size", "gc"):
        from bioflow.core.diskusage import (  # noqa: PLC0415
            db_usage, free_space, human, remove_db,
        )

        if action == "size":
            entries = db_usage(dest)
            if not entries:
                console.print(
                    f"No databases installed under [bold]{dest}[/bold]. "
                    "Provision one with 'bioflow db provision <name>'."
                )
                raise typer.Exit(code=0)
            total = sum(e.bytes for e in entries)
            console.print(f"[bold]Installed databases[/bold] under {dest}")
            for e in entries:
                console.print(f"  {e.size:>10}  {e.name:<18} {e.detail:<10} {e.path}")
            console.print(f"  {'-' * 10}")
            console.print(f"  {human(total):>10}  total")
            try:
                free, _ = free_space(dest)
                console.print(f"  {human(free):>10}  free on this filesystem")
            except OSError:
                pass
            raise typer.Exit(code=0)

        # gc
        if not name:
            console.print("[red]'bioflow db gc' needs a database name.[/red] "
                          "See 'bioflow db size'.")
            raise typer.Exit(code=1)
        if name not in _DB_CATALOG:
            console.print(f"[red]Unknown database '{name}'.[/red] "
                          "See 'bioflow db list'.")
            raise typer.Exit(code=1)
        installed = {e.name: e for e in db_usage(dest)}
        target = installed.get(name)
        if target is None:
            console.print(f"'{name}' is not installed under {dest} — nothing to remove.")
            raise typer.Exit(code=0)
        if not force:
            ok = typer.confirm(
                f"Delete {target.size} at {target.path}? "
                f"(re-provision with 'bioflow db provision {name}')"
            )
            if not ok:
                console.print("Left untouched.")
                raise typer.Exit(code=0)
        freed = remove_db(name, dest)
        if freed:
            console.print(f"Removed [bold]{name}[/bold] — reclaimed {freed.size}.")
        raise typer.Exit(code=0)

    if action == "ensure":
        if not name:
            rprint("[red]Error:[/] a TOOL id is required for ensure "
                   "(e.g. 'bioflow db ensure eggnog_mapper').")
            raise typer.Exit(code=1)
        stats = ensure_db_current(name, dest, auto_update=not no_update,
                                  check_latest=True)
        if not stats:
            rprint(f"[dim]{name} uses no versioned reference DB.[/]")
            return
        for st in stats:
            if not st["present"]:
                rprint(f"[yellow]○[/] {st['db']} — not provisioned "
                       f"(bioflow db provision {st['db']})")
            elif st["update_available"]:
                verb = "flagged (newer available)" if no_update else "updated"
                rprint(f"[green]✓[/] {st['db']} — {verb} "
                       f"→ {st['latest'] or st['catalog']}")
            else:
                rprint(f"[green]✓[/] {st['db']} — current ({st['installed']})")
        return

    if action == "status":
        keys = [name] if name else [k for k, e in _DB_CATALOG.items() if e.get("version")]
        console.print("\n[bold]Reference-DB versions:[/]\n")
        for k in keys:
            try:
                st = db_status(k, dest, check_latest=check_latest)
            except KeyError as exc:
                rprint(f"[red]Error:[/] {exc}")
                raise typer.Exit(code=1) from exc
            inst = st["installed"] or "[dim]not provisioned[/]"
            latest = f"  latest={st['latest']}" if st["latest"] else ""
            flag = "  [yellow]⬆ update available[/]" if st["update_available"] else ""
            console.print(f"  [cyan]{k:<16}[/] installed={inst}  "
                          f"catalog={st['catalog']}{latest}{flag}")
        return

    if action == "provision":
        if not name:
            rprint("[red]Error:[/] 'name' required for provision.")
            raise typer.Exit(code=1)
        cmd = provision_command(name, dest)
        if cmd is None:
            rprint(f"[yellow]{name}[/] is fetched via a plain URL — use "
                   f"[cyan]bioflow db fetch {name}[/].")
            raise typer.Exit(code=0)
        tools = _DB_CATALOG[name].get("used_by", [])
        rprint(f"[bold]Provision {name}[/] (v{catalog_version(name)}) "
               f"inside the {', '.join(tools)} container:\n")
        rprint(f"  [cyan]{cmd}[/]\n")
        if not run:
            rprint("[dim]Dry run — re-run with [bold]--run[/] to pull the image "
                   "and download the DB (several GB).[/]")
            return
        rprint("[yellow]--run provisioning is not wired to a backend yet; "
               "execute the printed command in the tool container.[/]")
        return

    if action == "update":
        if not name:
            rprint("[red]Error:[/] 'name' required for update.")
            raise typer.Exit(code=1)
        try:
            res = update_db(name, dest)
        except (KeyError, RuntimeError) as exc:
            rprint(f"[red]Error:[/] {exc}")
            raise typer.Exit(code=1) from exc
        if res["updated"]:
            rprint(f"[green]✓[/] {name} → {res['installed']}")
        else:
            rprint(f"[dim]{name} already current ({res['installed']}).[/]")
        return

    if action == "list":
        rows = list_dbs()
        console.print("\n[bold]Available reference databases:[/]\n")
        for r in rows:
            used = ", ".join(r["used_by"])
            tag = f"  [dim]({r['genome']}/{r['asset']})[/]" if r.get("genome") else ""
            console.print(
                f"  [cyan]{r['key']:<24}[/]  {r['size_gb']:5.2f} GB  "
                f"used by: {used}{tag}"
            )
            console.print(f"    {r['name']}")
            if r["notes"]:
                console.print(f"    [dim]{r['notes']}[/]")
        return

    if action == "manifest":
        import sys  # noqa: PLC0415
        manifest = refgenie_manifest(dest_root=dest)
        sys.stdout.write(json.dumps(manifest, indent=2) + "\n")
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
        rprint(f"[red]Unknown action '{action}'.[/] Use: "
               "list | fetch | verify | manifest | status | update | provision")
        raise typer.Exit(code=1)
