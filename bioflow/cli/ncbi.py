"""`bioflow ncbi` — search and download genomes / proteins from NCBI."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint

from bioflow.cli._app import app


@app.command("ncbi")
def ncbi_cmd(
    action: str = typer.Argument(..., help="search | genome | protein"),
    taxon: str = typer.Option(..., "--taxon", "-t",
        help="Scientific name or NCBI taxonomy ID (e.g. 'dickeya', '2038')."),
    db: str = typer.Option("genome", "--db",
        help="[search only] Database to query: genome | protein."),
    out: Optional[Path] = typer.Option(None, "--out", "-o",
        help="Output directory for downloaded files."),
    level: Optional[str] = typer.Option(None, "--level", "-l",
        help="[genome] Assembly level filter: complete | chromosome | scaffold | contig."),
    reference_only: bool = typer.Option(False, "--reference-only",
        help="[genome] Return only reference/representative assemblies."),
    max: int = typer.Option(20, "--max", "-n",
        help="Maximum number of assemblies (genome) or sequences (protein) to retrieve."),
    include: str = typer.Option("GENOME_FASTA", "--include",
        help="[genome download] Comma-separated data types: "
             "GENOME_FASTA, GENOME_GFF, PROT_FASTA, CDS_FASTA, RNA_FASTA, "
             "GENOME_GBFF, SEQUENCE_REPORT.  PROTEIN_FASTA is accepted as an "
             "alias of PROT_FASTA."),
    filter_term: str = typer.Option("refseq[filter]", "--filter",
        help="[protein] Entrez filter.  Use '' for all records."),
) -> None:
    """Download genomes and proteins from NCBI.

    \b
    search   List available assemblies or proteins for a taxon (no download).
    genome   Download genome FASTA (and optionally GFF/protein) files.
    protein  Download protein FASTA for annotation evidence (BRAKER3/MAKER).

    \b
    Examples:
      bioflow ncbi search  --taxon dickeya --db genome --level complete
      bioflow ncbi genome  --taxon dickeya --out /data/genomes --level complete --max 20
      bioflow ncbi protein --taxon pectobacteriaceae --out /data/proteins --max 2000
    """
    from bioflow.core.ncbi import (  # noqa: PLC0415
        NcbiError, download_genomes, download_proteins,
        list_genomes, list_proteins,
    )

    # ------------------------------------------------------------------ search
    if action == "search":
        if db == "genome":
            try:
                assemblies = list_genomes(
                    taxon,
                    assembly_level=level,
                    reference_only=reference_only,
                    max_results=max,
                )
            except NcbiError as exc:
                rprint(f"[red]NCBI error:[/] {exc}")
                raise typer.Exit(code=1)

            if not assemblies:
                rprint(f"[yellow]No genome assemblies found for '{taxon}'.[/]")
                raise typer.Exit(code=0)

            rprint(f"\n[bold]Genome assemblies for [cyan]{taxon}[/] — {len(assemblies)} result(s)[/]\n")
            for a in assemblies:
                ref_tag = " [bold green][REF][/]" if a.is_reference else ""
                size_mb = a.total_sequence_length / 1_000_000
                rprint(
                    f"  [cyan]{a.accession}[/]  "
                    f"{a.organism}"
                    + (f" ({a.strain})" if a.strain else "")
                    + f"  [dim]{a.assembly_level}[/]  {size_mb:.1f} Mb"
                    + ref_tag
                )

        elif db == "protein":
            try:
                total, records = list_proteins(
                    taxon, filter_term=filter_term, preview_size=max
                )
            except NcbiError as exc:
                rprint(f"[red]NCBI error:[/] {exc}")
                raise typer.Exit(code=1)

            if total == 0:
                rprint(f"[yellow]No proteins found for '{taxon}'.[/]")
                raise typer.Exit(code=0)

            rprint(
                f"\n[bold]Proteins for [cyan]{taxon}[/] — "
                f"{total} total (showing {len(records)})[/]\n"
            )
            for r in records:
                rprint(
                    f"  [dim]{r['uid']}[/]  {r['organism']}  "
                    f"[dim]{r['length']} aa[/]  {r['title'][:70]}"
                )
        else:
            rprint(f"[red]Unknown --db '{db}'.[/] Use: genome | protein")
            raise typer.Exit(code=1)

    # ------------------------------------------------------------------ genome
    elif action == "genome":
        if out is None:
            rprint("[red]--out is required for 'genome' download.[/]")
            raise typer.Exit(code=1)

        include_types = [s.strip().upper() for s in include.split(",")]
        rprint(
            f"\n[bold]Downloading genomes for [cyan]{taxon}[/] "
            f"(max {max}, level={level or 'any'}, include={include_types})[/]\n"
        )
        try:
            paths = download_genomes(
                taxon, out,
                assembly_level=level,
                reference_only=reference_only,
                max_assemblies=max,
                include=include_types,
            )
        except NcbiError as exc:
            rprint(f"[red]Download failed:[/] {exc}")
            raise typer.Exit(code=1)

        rprint(f"\n[green]✓ {len(paths)} file(s) downloaded → {out}[/]")
        for p in paths:
            rprint(f"  [dim]{p.name}[/]")

    # ------------------------------------------------------------------ protein
    elif action == "protein":
        if out is None:
            rprint("[red]--out is required for 'protein' download.[/]")
            raise typer.Exit(code=1)

        rprint(
            f"\n[bold]Downloading proteins for [cyan]{taxon}[/] "
            f"(max {max}, filter={filter_term!r})[/]\n"
        )
        try:
            fasta_path = download_proteins(
                taxon, out,
                filter_term=filter_term,
                max_results=max,
            )
        except NcbiError as exc:
            rprint(f"[red]Download failed:[/] {exc}")
            raise typer.Exit(code=1)

        rprint(f"\n[green]✓ Protein FASTA → {fasta_path}[/]")

    else:
        rprint(f"[red]Unknown action '{action}'.[/] Available: search | genome | protein")
        raise typer.Exit(code=1)


def _parse_recipe_extra(extra: "list[str]") -> "dict[str, object]":
    """Parse pass-through ``--key value`` / ``--key=value`` / ``--flag``
    tokens (collected by Click's ``ignore_unknown_options``) into a
    kwargs dict.

    ``--sample-id`` becomes ``sample_id``.  Pure-integer values are
    coerced to ``int`` so recipes doing arithmetic on numeric options
    (e.g. ``cb_len + 1``) keep working; everything else stays a string
    and recipes coerce to ``Path`` themselves.
    """
    out: "dict[str, object]" = {}
    i = 0
    while i < len(extra):
        tok = extra[i]
        if not tok.startswith("--"):
            i += 1
            continue
        body = tok[2:]
        if "=" in body:
            key, val = body.split("=", 1)
            out[key.replace("-", "_")] = val
            i += 1
        elif i + 1 < len(extra) and not extra[i + 1].startswith("--"):
            out[body.replace("-", "_")] = extra[i + 1]
            i += 2
        else:
            out[body.replace("-", "_")] = "true"   # bare flag
            i += 1
    # light numeric coercion — paths never look like pure integers
    for k, v in list(out.items()):
        if isinstance(v, str) and v.isdigit():
            out[k] = int(v)
    return out


