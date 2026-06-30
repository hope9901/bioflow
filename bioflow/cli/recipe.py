"""`bioflow recipe list / show / run` — the Tier-B entry point.

Exposes the recipe-extra parser ``_parse_recipe_extra`` for the test suite.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint

from bioflow.cli._app import app, console


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


@app.command(
    "recipe",
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
def recipe_cmd(
    ctx: typer.Context,
    action: str = typer.Argument(
        ..., help="list | show <name> | run <name>"
    ),
    name: Optional[str] = typer.Argument(None, help="Recipe name."),
    out: Path = typer.Option(
        Path("bioflow_recipe_out"),
        "--out", "-o",
        help="Output workspace (created if missing).",
    ),
    taxon: Optional[str] = typer.Option(None, "--taxon", "-t",
        help="NCBI taxon (for taxon-driven recipes)."),
    max_genomes: int = typer.Option(30, "--max", "-n",
        help="Cap on assemblies to fetch."),
    reference_only: bool = typer.Option(True, "--reference-only/--all",
        help="Use only RefSeq reference assemblies."),
    identity: int = typer.Option(90, "--identity",
        help="Identity threshold (recipe-specific; e.g. Roary -i)."),
    genome_dir: Optional[Path] = typer.Option(None, "--genome-dir",
        help="Directory of *.fna inputs (ani_matrix, amr_vf_catalogue)."),
    gff_dir: Optional[Path] = typer.Option(None, "--gff-dir",
        help="Directory of Prokka GFF inputs (phylogeny)."),
    traits_csv: Optional[Path] = typer.Option(None, "--traits-csv",
        help="Scoary-format binary traits CSV (gwas)."),
    gpa_csv: Optional[Path] = typer.Option(None, "--gpa-csv",
        help="Roary gene_presence_absence.csv (gwas, phylogeny fallback, cog_enrichment)."),
    tree: Optional[Path] = typer.Option(None, "--tree",
        help="Ultrametric Newick tree (cafe_evolution)."),
    count_table: Optional[Path] = typer.Option(None, "--count-table",
        help="CAFE-format family count matrix (cafe_evolution)."),
    pangenome_faa: Optional[Path] = typer.Option(None, "--pangenome-faa",
        help="One protein per Roary cluster (cog_enrichment)."),
    cog_faa: Optional[Path] = typer.Option(None, "--cog-faa",
        help="COG-2024 reference FASTA (cog_enrichment)."),
    cog_def: Optional[Path] = typer.Option(None, "--cog-def",
        help="NCBI cog-24.def.tab (cog_enrichment)."),
    dry_run: bool = typer.Option(False, "--dry-run",
        help="Print the DAG without running."),
    provenance: bool = typer.Option(True, "--provenance/--no-provenance",
        help="Record run provenance (input SHA-256, image digests, "
             "commands, timestamps) and write provenance.json + "
             "ro-crate-metadata.json into the workspace."),
    set_overrides: "list[str]" = typer.Option(
        [], "--set",
        help="Override a stage parameter without editing the recipe: "
             "--set <stage>.<param>=<value> (repeatable).  "
             "E.g. --set assemble.kmer=21,33,55.  Overrides land in the "
             "cache key + provenance, so reproducibility is preserved.",
    ),
) -> None:
    """Curated end-to-end pipelines (the Tier-B entry point).

    \b
    Examples:
      bioflow recipe list
      bioflow recipe show pangenome
      bioflow recipe run pangenome --taxon Dickeya --max 13
      bioflow recipe run pangenome --taxon Pectobacterium --dry-run
    """
    from bioflow import recipes  # noqa: PLC0415  — lazy import
    from bioflow.sdk import set_workspace  # noqa: PLC0415

    if action == "list":
        if not recipes.names():
            rprint("[yellow]No recipes registered.[/]")
            raise typer.Exit(code=0)
        console.print("\n[bold]Available recipes:[/]\n")
        for n in recipes.names():
            p = recipes.get(n)
            console.print(
                f"  [cyan]{n:<20s}[/] [dim]({len(p.stages)} stages)[/]  "
                f"{p.description}"
            )
        return

    if not name:
        rprint(f"[red]'{action}' requires a recipe name.[/]")
        raise typer.Exit(code=1)

    try:
        pipe = recipes.get(name)
    except KeyError as exc:
        rprint(f"[red]{exc}[/]")
        raise typer.Exit(code=1)

    if action == "show":
        pipe.show_graph()
        return

    if action == "run":
        if dry_run:
            rprint(f"\n[bold]Dry-run for recipe[/] [cyan]{name}[/]:\n")
            pipe.show_graph()
            return

        out = out.resolve()
        out.mkdir(parents=True, exist_ok=True)
        set_workspace(out)
        rprint(f"\n[bold]Running recipe[/] [cyan]{name}[/]  workspace=[dim]{out}[/]")

        # Stage-parameter overrides (--set <stage>.<param>=<value>)
        overrides: "dict[str, object]" = {}
        for item in set_overrides:
            if "=" not in item:
                rprint(f"[red]--set expects <key>=<value>, got {item!r}.[/]")
                raise typer.Exit(code=1)
            key, val = item.split("=", 1)
            overrides[key.strip()] = val
        if overrides:
            from bioflow.sdk import set_param_overrides  # noqa: PLC0415
            set_param_overrides(overrides)
            rprint(f"[dim]parameter overrides: {overrides}[/]")

        # Build kwargs intelligently — pass only what the pipeline accepts.
        # Explicit options below cover the comparative-genomics recipes;
        # any other recipe's parameters arrive as pass-through --key value
        # tokens parsed from ctx.args.
        import inspect  # noqa: PLC0415
        sig = inspect.signature(pipe.func)
        candidate: "dict[str, object]" = {
            "taxon": taxon,
            "out_dir": out,
            "max_genomes": max_genomes,
            "reference_only": reference_only,
            "identity": identity,
            "genome_dir": genome_dir,
            "gff_dir": gff_dir,
            "traits_csv": traits_csv,
            "gpa_csv": gpa_csv,
            "tree": tree,
            "count_table": count_table,
            "pangenome_faa": pangenome_faa,
            "cog_faa": cog_faa,
            "cog_def": cog_def,
        }
        # Pass-through --key value tokens override / extend the explicit set
        candidate.update(_parse_recipe_extra(ctx.args))
        kwargs = {
            k: v for k, v in candidate.items()
            if k in sig.parameters and v is not None
        }
        # Warn about tokens that don't match any recipe parameter
        unknown = [
            k for k in _parse_recipe_extra(ctx.args)
            if k not in sig.parameters
        ]
        if unknown:
            rprint(
                f"[yellow]Ignored unknown option(s) for {name!r}: "
                f"{', '.join('--' + u.replace('_', '-') for u in unknown)}[/]"
            )
        # Validate required parameters that have no default
        missing = [
            n for n, p in sig.parameters.items()
            if p.default is inspect.Parameter.empty and n not in kwargs
        ]
        if missing:
            hint = "  ".join(
                f"--{m.replace('_', '-')} <value>" for m in missing
            )
            rprint(
                f"[red]Recipe {name!r} requires: {', '.join(missing)}.[/]\n"
                f"[dim]Pass each as an option, e.g.:[/] {hint}"
            )
            raise typer.Exit(code=1)

        from bioflow.core import provenance as _prov  # noqa: PLC0415

        recorder = None
        if provenance:
            recorder = _prov.ProvenanceRecorder(pipeline=name, workspace=out)
            _prov.set_recorder(recorder)

        try:
            result = pipe(**kwargs)
        except Exception as exc:
            rprint(f"[red]Recipe failed:[/] {exc}")
            if recorder is not None:
                written = _prov.write_all(recorder)
                _prov.set_recorder(None)
                for w in written:
                    rprint(f"[dim]  provenance → {w}[/]")
            raise typer.Exit(code=1)

        if recorder is not None:
            written = _prov.write_all(recorder)
            _prov.set_recorder(None)
            for w in written:
                rprint(f"[dim]  provenance → {w.name}[/]")

        rprint(f"\n[green]✓ Recipe done.[/]  result.out_dir = {getattr(result, 'out_dir', '?')}")
        return

    rprint(f"[red]Unknown action {action!r}.[/]  Use: list | show | run")
    raise typer.Exit(code=1)


