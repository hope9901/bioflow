"""Download every RefSeq assembly for a taxon.  Host-side only — no Docker.

Wraps :func:`bioflow.core.ncbi.download_genomes` as a registered
Pipeline so Tier-B users can invoke it via the CLI instead of
remembering the helper API.

    $ bioflow recipe run download_taxon --taxon Pectobacterium --max 50
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from bioflow import pipeline
from bioflow.core.ncbi import download_genomes
from bioflow.recipes import register


@pipeline(
    stages=(),     # zero containers — pure host-side I/O
    description="Download every RefSeq assembly for a taxon (no Docker)",
)
def download_taxon(
    taxon: str,
    *,
    out_dir: Path,
    max_genomes: int = 200,
    reference_only: bool = True,
    include: Iterable[str] = ("GENOME_FASTA",),
):
    """Fetch genome FASTAs (and optionally GFF) for *taxon*.

    Returns the list of downloaded paths.  Each download is automatically
    batched (the HTTP-414 fix) and retried on transient 5xx via the
    existing ``bioflow.core.ncbi`` machinery.
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = download_genomes(
        taxon, out_dir,
        reference_only=reference_only,
        max_assemblies=max_genomes,
        include=tuple(include),
    )
    return paths


register("download_taxon", download_taxon)
