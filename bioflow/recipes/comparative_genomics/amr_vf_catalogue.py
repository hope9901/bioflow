"""Genome-wide AMR + virulence factor + plasmid catalogue via ABRicate.

Replaces session-1's `run_abricate_full.py` (262 × 3 DBs in 16 min) with
one Pipeline that fans out N genomes × M databases, parallel='auto'.

    $ bioflow recipe run amr_vf_catalogue --genome-dir <fna_dir>
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence

from bioflow import stage, pipeline
from bioflow.recipes import register


@stage(image="staphb/abricate:1.4.0", cpu=1, ram_gb=1)
def abricate_one(genome_fna: Path, db: str, *, out_dir):
    """Run ABRicate on one genome against one database."""
    return (
        f"sh -c 'abricate --db {db} --threads 1 --quiet "
        f"{genome_fna} > {out_dir}/{genome_fna.stem}.{db}.tsv'"
    )


@pipeline(
    stages=[abricate_one],
    description="ABRicate × N genomes × M databases (AMR + VF + plasmid)",
)
def amr_vf_catalogue(
    *,
    out_dir: Path,
    genome_dir: Optional[Path] = None,
    genome_paths: Optional[Iterable[Path]] = None,
    dbs: Sequence[str] = ("vfdb", "card", "plasmidfinder"),
):
    """Scan every genome against every requested ABRicate database.

    Returns the full list of :class:`StageResult` so callers can
    aggregate per-DB / per-strain counts downstream.
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if genome_paths is not None:
        fnas = sorted(Path(p) for p in genome_paths)
    elif genome_dir is not None:
        fnas = sorted(Path(genome_dir).glob("*.fna"))
    else:
        raise ValueError("Provide genome_paths= or genome_dir=")
    if not fnas:
        raise RuntimeError("No genomes given to amr_vf_catalogue")

    pairs = [(g, db) for g in fnas for db in dbs]
    return abricate_one.starmap(pairs, parallel="auto", progress=True)


register("amr_vf_catalogue", amr_vf_catalogue)
