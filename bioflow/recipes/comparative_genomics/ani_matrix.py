"""All-vs-all ANI matrix via FastANI.

Mirrors session-1 `run_full_ani.py` (was ~70 lines of orchestration) as
a single-stage recipe.

    $ bioflow recipe run ani_matrix --genome-dir <fna_dir>
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from bioflow import pipeline, stage, stage_input
from bioflow.io import write_text
from bioflow.recipes import register


@stage(image="staphb/fastani:1.34", cpu=8, ram_gb=12)
def fastani_all_vs_all(genome_list_path: Path, *, out_dir):
    """Run FastANI in all-vs-all mode against the genomes listed in
    *genome_list_path* (one container-side path per line)."""
    return (
        f"fastANI --ql {genome_list_path} --rl {genome_list_path} "
        f"-o {out_dir}/ani_matrix.tsv -t 8"
    )


@pipeline(
    stages=[fastani_all_vs_all],
    description="All-vs-all ANI matrix (FastANI 1.34)",
)
def ani_matrix(
    *,
    out_dir: Path,
    genome_dir: Optional[Path] = None,
    genome_paths: Optional[Iterable[Path]] = None,
):
    """All-vs-all ANI on *genome_paths* or every ``*.fna`` under *genome_dir*.

    The genome list FASTA paths must be reachable from inside the
    container — the SDK's path translator handles that as long as the
    workspace covers the genomes.
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
        raise RuntimeError("No genomes given to ani_matrix")

    # FastANI reads genome paths from the list FILE, not the command, so
    # the SDK's command-path translator + auto-mount don't apply to them.
    # stage_input() copies each genome into the workspace (always mounted
    # at /work) and returns the container path to write into the list,
    # which FastANI (working dir /work) can then open.
    container_paths = [stage_input(g, subdir="ani_genomes") for g in fnas]

    list_path = out_dir / "genome_list.txt"
    write_text(list_path, "\n".join(container_paths) + "\n")
    return fastani_all_vs_all(list_path)


register("ani_matrix", ani_matrix)
