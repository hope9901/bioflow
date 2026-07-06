"""Metagenome assembly + binning recipe.

End-to-end shotgun-metagenomic assembly workflow using the binning
tools added in 0.1.11:
    fastp (QC)
        → MEGAHIT (metagenome assembly)
        → minimap2 (map reads back to contigs) + samtools
        → MetaBAT2 (genome binning)
        → CheckM2 (bin completeness / contamination)

Researcher (Tier B) usage::

    bioflow recipe run metagenome_assembly \\
        --r1 sample_R1.fq.gz --r2 sample_R2.fq.gz \\
        --sample-id env001 --out ./out
"""
from __future__ import annotations

from pathlib import Path

from bioflow import stage, pipeline
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="quay.io/biocontainers/fastp:1.3.6--h43da1c4_0",
       cpu=4, ram_gb=4)
def qc_trim(r1: Path, r2: Path, *, out_dir):
    """fastp QC + adapter trim."""
    return (
        f"fastp -i {r1} -I {r2} "
        f"-o {out_dir}/clean_R1.fq.gz -O {out_dir}/clean_R2.fq.gz "
        f"--json {out_dir}/fastp.json --html {out_dir}/fastp.html --thread 4"
    )


@stage(image="quay.io/biocontainers/megahit:1.2.9--h2e03b76_1",
       cpu=16, ram_gb=64, depends_on=qc_trim,
       retry=2, retry_with={"ram_gb": "2x"})
def assemble(clean, *, out_dir):
    """MEGAHIT metagenome assembly."""
    return (
        f"sh -c 'rm -rf {out_dir}/megahit && "
        f"megahit -1 {clean.out_dir}/clean_R1.fq.gz "
        f"-2 {clean.out_dir}/clean_R2.fq.gz "
        f"-o {out_dir}/megahit -t 16 --memory 0.85'"
    )


@stage(image=("quay.io/biocontainers/mulled-v2-"
              "66534bcbb7031a148b13e2ad42583020b9cd25c4:"
              "b411340b52d82a9c276d87c7a3dcffc880be762f-0"),
       cpu=16, ram_gb=32, depends_on=assemble)
def map_back(asm, clean, *, out_dir):
    """Map QC reads back to contigs for coverage (minimap2 + samtools).

    Uses a mulled minimap2 + samtools BioContainer (minimap2 2.31 +
    samtools 1.23) — the plain ``biocontainers/minimap2`` image ships no
    samtools, so the ``minimap2 | samtools sort`` chain fails on it.
    """
    contigs = f"{asm.out_dir}/megahit/final.contigs.fa"
    return (
        f"bash -c '"
        f"minimap2 -ax sr -t 16 {contigs} "
        f"{clean.out_dir}/clean_R1.fq.gz {clean.out_dir}/clean_R2.fq.gz "
        f"| samtools sort -@ 16 -o {out_dir}/mapped.bam - && "
        f"samtools index {out_dir}/mapped.bam'"
    )


@stage(image="quay.io/biocontainers/metabat2:2.17--h6f16272_1",
       cpu=8, ram_gb=32, depends_on=map_back)
def bin_genomes(mapped, asm, *, out_dir):
    """MetaBAT2 genome binning from contig coverage."""
    contigs = f"{asm.out_dir}/megahit/final.contigs.fa"
    return (
        f"bash -c '"
        f"jgi_summarize_bam_contig_depths "
        f"--outputDepth {out_dir}/depth.txt {mapped.out_dir}/mapped.bam && "
        f"metabat2 -i {contigs} -a {out_dir}/depth.txt "
        f"-o {out_dir}/bins/bin --numThreads 8'"
    )


@stage(image="quay.io/biocontainers/checkm2:1.0.2--pyh7cba7a3_0",
       cpu=8, ram_gb=32, depends_on=bin_genomes)
def assess_bins(bins, *, out_dir, checkm2_db: Path = Path("/refs/checkm2")):
    """CheckM2 completeness + contamination per bin."""
    return (
        f"checkm2 predict --threads 8 --input {bins.out_dir}/bins "
        f"--output-directory {out_dir}/checkm2 -x fa "
        f"--database_path {checkm2_db}"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[qc_trim, assemble, map_back, bin_genomes, assess_bins],
    description="Metagenome assembly + binning: fastp → MEGAHIT → minimap2 → MetaBAT2 → CheckM2",
)
def metagenome_assembly(
    r1: Path,
    r2: Path,
    *,
    out_dir: Path,
    sample_id: str = "sample",
    checkm2_db: Path = Path("/refs/checkm2"),
):
    """fastp → MEGAHIT → minimap2 → MetaBAT2 → CheckM2 end-to-end."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    clean = qc_trim(Path(r1), Path(r2))
    asm = assemble(clean)
    mapped = map_back(asm, clean)
    bins = bin_genomes(mapped, asm)
    return assess_bins(bins, checkm2_db=Path(checkm2_db))


register("metagenome_assembly", metagenome_assembly)
