"""Gene family expansion / contraction analysis via CAFE5.

Mirrors session-1's manual CAFE5 wiring (CAFE5 was added to the registry
in commit 9d52926 for the Dickeya VFDB analysis) but expressed as a
recipe so any taxon can drive it.

Inputs the user must supply:
  * an **ultrametric** phylogeny in Newick format (CAFE5 won't run on a
    non-ultrametric tree — use ape::chronos / r8s / TreeTime upstream)
  * a CAFE-format gene-family count matrix:
        FamilyID<TAB>Description<TAB>species1<TAB>species2<TAB>…

Both can come from the phylogeny / pangenome recipes — see
``examples/dickeya_vfdb_cafe.py`` (session-1 artefact) for the
end-to-end glue.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from bioflow import stage, pipeline
from bioflow.recipes import register


@stage(
    image="quay.io/biocontainers/cafe:5.1.0--h5ca1c30_1",
    cpu=4, ram_gb=8,
    # CAFE5 occasionally OOMs on very wide gene-family tables — give it
    # a chance to retry with twice the memory.
    retry=1, retry_with={"ram_gb": "2x"},
)
def run_cafe5(
    tree: Path, count_table: Path, *,
    out_dir,
    p_value: float = 0.05,
):
    """Run CAFE5 on an ultrametric tree + family count matrix."""
    return (
        f"sh -c 'cd {out_dir} && "
        f"cafe5 -i {count_table} -t {tree} "
        f"-p -o results --pvalue {p_value}'"
    )


@pipeline(
    stages=[run_cafe5],
    description="Gene family expansion/contraction (CAFE5)",
)
def cafe_evolution(
    tree: Path,
    count_table: Path,
    *,
    out_dir: Path,
    p_value: float = 0.05,
):
    """Run CAFE5 on a user-supplied ultrametric tree + count matrix.

    Both inputs must already be inside the active workspace so the SDK
    can mount them.  If your tree is non-ultrametric, ultrametricise it
    upstream (e.g. ``treetime ultrametric`` or ``ape::chronos``).
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    return run_cafe5(
        Path(tree).resolve(),
        Path(count_table).resolve(),
        p_value=p_value,
    )


register("cafe_evolution", cafe_evolution)
