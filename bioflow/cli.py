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

import sys
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console

# ── Windows-safe console encoding ───────────────────────────────────────────
# On non-UTF-8 Windows shells (e.g. Korean cp949) Rich's ✓/✗/⚠ glyphs raise
# UnicodeEncodeError mid-print and abort the command.  Force stdout/stderr to
# UTF-8 when the interpreter supports it (Python ≥ 3.7) — this is a no-op on
# already-UTF-8 terminals and keeps non-Windows behaviour unchanged.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="bioflow: genome assembly/annotation & RNA-seq DEG pipeline platform.",
)
# Rich Console: keep colour but degrade glyphs gracefully on legacy code pages
console = Console(emoji=False, legacy_windows=False)


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


@app.command("recommend")
def recommend_cmd(
    preset: str = typer.Option(..., "--preset", "-p"),
    config: Path = typer.Option(..., "--config", "-c", exists=True),
    registry: Path = typer.Option(Path("registry"), "--registry", "-r"),
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
    registry: Path = typer.Option(Path("registry"), "--registry", "-r"),
) -> None:
    """Interactively pick tools per stage (only hardware-compatible ones shown)."""
    from bioflow.core.planner import interactive_build  # noqa: PLC0415

    interactive_build(pipeline, out, registry_dir=registry)
    rprint(f"[green]✓ Saved custom pipeline config →[/] {out}")


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


@app.command("update")
def update_cmd(
    action: str = typer.Argument(..., help="approve"),
    candidate: Optional[Path] = typer.Option(
        None, "--candidate", "-c",
        help="Path to a single candidate YAML to approve.",
    ),
    candidates_dir: Optional[Path] = typer.Option(
        None, "--candidates-dir",
        help="Approve every .yaml in this directory.",
    ),
    registry_dir: Path = typer.Option(
        Path("registry"), "--registry",
        help="Root of the tool registry.",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing entries."),
    delete_candidate: bool = typer.Option(
        False, "--delete-candidate",
        help="Delete candidate file(s) after successful approval.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without writing."),
) -> None:
    """Registry update utilities.

    \b
    approve   Promote a candidate YAML (or a whole directory) to the registry.
    """
    from bioflow.core.approve import (  # noqa: PLC0415
        ApprovalError,
        approve_all_candidates,
        approve_candidate,
    )

    if action == "approve":
        if candidate and candidates_dir:
            rprint("[red]Specify --candidate OR --candidates-dir, not both.[/]")
            raise typer.Exit(code=1)

        if candidate:
            if dry_run:
                rprint(f"[dim][DRY RUN] Would approve {candidate}[/]")
            try:
                dest = approve_candidate(
                    candidate,
                    registry_dir=registry_dir,
                    overwrite=overwrite,
                    delete_candidate=delete_candidate,
                    dry_run=dry_run,
                )
                if not dry_run:
                    rprint(f"[green]✓ Approved:[/] {candidate.name} → [cyan]{dest}[/]")
                else:
                    rprint(f"[dim]Would write → {dest}[/]")
            except ApprovalError as exc:
                rprint(f"[red]Approval failed:[/] {exc}")
                raise typer.Exit(code=1)

        elif candidates_dir:
            if not candidates_dir.is_dir():
                rprint(f"[red]Not a directory:[/] {candidates_dir}")
                raise typer.Exit(code=1)
            results = approve_all_candidates(
                candidates_dir,
                registry_dir=registry_dir,
                overwrite=overwrite,
                delete_candidates=delete_candidate,
                dry_run=dry_run,
            )
            if not results:
                rprint("[yellow]No candidate YAML files found.[/]")
                raise typer.Exit(code=0)

            approved = [r for r in results if r["status"] == "approved"]
            skipped  = [r for r in results if r["status"] == "skipped"]
            errors   = [r for r in results if r["status"] == "error"]

            for r in approved:
                rprint(f"[green]✓ approved[/]  {r['file']} → {r.get('dest','')}")
            for r in skipped:
                rprint(f"[yellow]⚠ skipped[/]   {r['file']}: {r.get('error','')}")
            for r in errors:
                rprint(f"[red]✗ error[/]     {r['file']}: {r.get('error','')}")

            rprint(
                f"\n[bold]Total:[/] {len(results)}  "
                f"[green]approved={len(approved)}[/]  "
                f"[yellow]skipped={len(skipped)}[/]  "
                f"[red]errors={len(errors)}[/]"
            )
            if errors:
                raise typer.Exit(code=1)
        else:
            rprint("[red]--candidate or --candidates-dir is required for 'approve'.[/]")
            raise typer.Exit(code=1)

    else:
        rprint(f"[red]Unknown action '{action}'.[/] Available: approve")
        raise typer.Exit(code=1)


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


if __name__ == "__main__":
    app()
