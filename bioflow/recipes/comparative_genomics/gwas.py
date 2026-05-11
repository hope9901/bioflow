"""Pangenome-wide GWAS via Scoary on a Roary gene_presence_absence.csv.

    $ bioflow recipe run gwas \\
        --traits-csv my_traits.csv \\
        --gpa-csv pangenome/gene_presence_absence.csv

The traits CSV is the Scoary format (samples as rows, binary 0/1 per
phenotype column).
"""
from __future__ import annotations

from pathlib import Path

from bioflow import stage, pipeline
from bioflow.recipes import register


@stage(
    image="quay.io/biocontainers/scoary:1.6.16--py_2",
    cpu=4, ram_gb=8,
    retry=1,
)
def run_scoary(traits_csv: Path, gpa_csv: Path, *, out_dir):
    """Scoary binary-trait GWAS over a Roary GPA CSV."""
    return (
        f"sh -c 'cd {out_dir} && cp {traits_csv} _traits.csv && "
        f"scoary -t _traits.csv -g {gpa_csv} "
        f"--no_pairwise --no-time -o results --threads 4'"
    )


@pipeline(
    stages=[run_scoary],
    description="Scoary GWAS over a Roary pangenome",
)
def gwas(
    traits_csv: Path,
    gpa_csv: Path,
    *,
    out_dir: Path,
):
    """Run Scoary on *gpa_csv* with phenotypes from *traits_csv*."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    return run_scoary(Path(traits_csv).resolve(), Path(gpa_csv).resolve())


register("gwas", gwas)
