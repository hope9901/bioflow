"""`bioflow cache` — inspect and reclaim the workspace stage cache."""
from __future__ import annotations

from pathlib import Path

import typer

from bioflow.cli._app import app, console


@app.command("cache")
def cache_cmd(
    action: str = typer.Argument("size", help="size | clear"),
    workspace: Path = typer.Option(
        Path("bioflow_work"), "--workspace", "-w",
        help="Workspace whose .cache directory to inspect.",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="[clear] Skip the confirmation.",
    ),
    top: int = typer.Option(15, "--top", help="[size] How many entries to list."),
) -> None:
    """Show what the stage cache is holding, or empty it.

    \b
    size   Per-stage cache directories, largest first, plus the total.
    clear  Delete every cached stage result. Safe but not free: the next run
           re-executes every stage instead of reusing a hit.

    Each entry is one content-addressed stage result (``<stage>__<hash>``), so
    deleting is only ever a time cost, never a correctness one.
    """
    from bioflow.core.diskusage import cache_usage, free_space, human  # noqa: PLC0415

    entries = cache_usage(workspace)
    total = sum(e.bytes for e in entries)

    if action == "size":
        if not entries:
            console.print(f"Stage cache under [bold]{workspace}[/bold] is empty.")
            raise typer.Exit(code=0)
        console.print(
            f"[bold]Stage cache[/bold] under {workspace}/.cache "
            f"— {len(entries)} entries, {human(total)}"
        )
        for e in entries[:top]:
            console.print(f"  {e.size:>10}  {e.name}")
        if len(entries) > top:
            console.print(f"  … and {len(entries) - top} more")
        try:
            free, _ = free_space(workspace)
            console.print(f"  {human(free):>10}  free on this filesystem")
        except OSError:
            pass
        raise typer.Exit(code=0)

    if action == "clear":
        if not entries:
            console.print("Nothing cached — nothing to clear.")
            raise typer.Exit(code=0)
        if not force:
            ok = typer.confirm(
                f"Delete {len(entries)} cached stage results ({human(total)})? "
                "The next run re-executes them."
            )
            if not ok:
                console.print("Left untouched.")
                raise typer.Exit(code=0)
        from bioflow.sdk import clear_cache  # noqa: PLC0415

        removed = clear_cache(workspace)
        console.print(f"Cleared {removed} entries — reclaimed {human(total)}.")
        raise typer.Exit(code=0)

    console.print(f"[red]Unknown action '{action}'.[/red] Use: size | clear")
    raise typer.Exit(code=1)
