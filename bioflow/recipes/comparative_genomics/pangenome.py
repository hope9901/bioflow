"""Pangenome recipe — NCBI taxon → Prokka × N → Roary, end-to-end.

This is the canonical Phase 1 verification artefact.  The 175-line
``analysis/dickeya/run_full_pangenome.py`` from session 1 collapses to
roughly 30 lines here, with the SDK absorbing all the parallelism,
caching and chaining boilerplate.

Researcher (Tier B) usage
-------------------------
    $ bioflow recipe run pangenome --taxon Dickeya --max 30

Programmatic (Tier A) usage
---------------------------
    from bioflow.recipes import get
    pipe = get("pangenome")
    pipe(taxon="Pectobacterium", max_genomes=15, out_dir=Path("./pec"))
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from bioflow import stage, pipeline
from bioflow.core.ncbi import download_genomes
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="staphb/prokka:1.15.6", cpu=2, ram_gb=4)
def annotate(genome_fna: Path, *, out_dir):
    """Re-annotate one genome with Prokka.  One container per genome."""
    return (
        f"prokka --outdir {out_dir}/p --prefix {genome_fna.stem} "
        f"--kingdom Bacteria --cpus 2 --force --quiet {genome_fna}"
    )


@stage(image="staphb/roary:3.13.0", cpu=8, ram_gb=16, depends_on=annotate)
def run_roary(annotated, *, out_dir, identity: int = 90):
    """Cluster orthologs across all annotated genomes."""
    gff_paths = " ".join(f"{r.out_dir}/p/*.gff" for r in annotated)
    return (
        f"sh -c 'rm -rf {out_dir}/roary && "
        f"roary -p 8 -i {identity} -f {out_dir}/roary {gff_paths}'"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[annotate, run_roary],
    description="Pangenome from a taxon: NCBI fetch → parallel Prokka → Roary",
)
def pangenome(
    taxon: str,
    *,
    out_dir: Path,
    max_genomes: int = 30,
    reference_only: bool = True,
    identity: int = 90,
    _genome_paths: "Iterable[Path] | None" = None,
):
    """End-to-end pangenome on every RefSeq assembly of *taxon*.

    Parameters
    ----------
    taxon :
        NCBI taxonomy name or taxid (e.g. ``"Dickeya"`` or ``"204037"``).
    out_dir :
        Workspace; everything (downloaded genomes, Prokka output,
        Roary output) lands here.
    max_genomes :
        Cap on assemblies to retrieve.  Use a small value for trial runs.
    reference_only :
        If True, only RefSeq reference assemblies (one per species).
    identity :
        Roary BLAST percent-identity threshold.  90 keeps distantly
        related strains in the same family; 95 is Roary's stricter
        default.
    _genome_paths :
        Internal escape hatch for tests — supply pre-existing FASTA
        paths and skip the NCBI fetch.
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Acquire genomes ────────────────────────────────────────────────
    if _genome_paths is not None:
        fnas = sorted(Path(p) for p in _genome_paths)
    else:
        genome_dir = out_dir / "genomes"
        download_genomes(
            taxon, genome_dir,
            reference_only=reference_only,
            max_assemblies=max_genomes,
            include=("GENOME_FASTA",),
        )
        fnas = sorted(genome_dir.glob("*.fna"))

    if not fnas:
        raise RuntimeError(
            f"No genomes found for taxon {taxon!r}.  Try "
            f"`bioflow ncbi search --taxon {taxon}` to verify."
        )

    # ── 2. Parallel re-annotation ─────────────────────────────────────────
    annotated = annotate.map(fnas, parallel="auto", progress=True)

    # ── 3. Pangenome clustering ───────────────────────────────────────────
    return run_roary(annotated, identity=identity)


# Auto-register so `bioflow.recipes.get("pangenome")` works
register("pangenome", pangenome)
