"""`bioflow lineage` — recommend a BUSCO / compleasm lineage for a genome."""
from __future__ import annotations

from typing import Optional

import typer
from rich import print as rprint

from bioflow.cli._app import app


@app.command("lineage")
def lineage_cmd(
    taxon: Optional[str] = typer.Argument(
        None, help="Free-text taxon hint, e.g. 'fungus', 'insect', 'human'."),
    species: str = typer.Option(
        "eukaryote", "--species", "-s",
        help="Species class when no taxon is given (prokaryote|eukaryote|eukaryote_small)."),
) -> None:
    """Suggest which BUSCO/compleasm lineage (odb10) to score completeness against.

    \b
    bioflow lineage fungus            → fungi_odb10
    bioflow lineage "baker's yeast"   → saccharomycetes_odb10
    bioflow lineage --species prokaryote
    """
    from bioflow.core.lineage import recommend_lineage  # noqa: PLC0415

    rec = recommend_lineage(species=species, taxon=taxon)
    rprint(f"\n[bold]Recommended lineage:[/] [cyan]{rec['lineage']}[/]")
    rprint(f"  [dim]chosen by:[/] {rec['source']}")
    if rec["db_key"]:
        rprint(f"  [green]catalogued[/] — get it with: "
               f"[cyan]bioflow db fetch {rec['db_key']}[/]")
    else:
        rprint(f"  [dim]obtain:[/] {rec['how']}")
    rprint(f"\n  Use with:  [cyan]busco -l {rec['lineage']} …[/]  or  "
           f"[cyan]compleasm run -l {rec['lineage']} …[/]\n")
