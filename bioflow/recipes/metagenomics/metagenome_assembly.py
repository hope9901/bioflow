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


@stage(image="quay.io/biocontainers/metabat2:2.18--h38e344b_2",
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


@stage(image="quay.io/biocontainers/maxbin2:2.2.7--h503566f_8",
       cpu=8, ram_gb=32, depends_on=assemble)
def bin_genomes_maxbin2(asm, clean, *, out_dir):
    """MaxBin2 genome binning (``--set binner=maxbin2``).

    MaxBin2 does its own read mapping from the clean FASTQs (``-reads``), so it
    needs neither MetaBAT2's depth table nor samtools.  It names bins
    ``maxbin.NNN.fasta``; we copy those into the ``bins/*.fa`` layout the CheckM2
    stage expects (``-x fa``, ``--input .../bins``), so downstream is identical
    to the MetaBAT2 path.
    """
    contigs = f"{asm.out_dir}/megahit/final.contigs.fa"
    return (
        f"bash -c '"
        f"mkdir -p {out_dir}/bins && "
        f"run_MaxBin.pl -contig {contigs} "
        f"-reads {clean.out_dir}/clean_R1.fq.gz "
        f"-reads2 {clean.out_dir}/clean_R2.fq.gz "
        f"-out {out_dir}/maxbin -thread 8 && "
        f"i=0; for f in {out_dir}/maxbin.*.fasta; do "
        f"[ -e \"$f\" ] || continue; i=$((i+1)); cp \"$f\" {out_dir}/bins/bin.$i.fa; done'"
    )


@stage(image="quay.io/biocontainers/checkm2:1.1.0--pyh7e72e81_1",
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
    stages=[qc_trim, assemble, map_back, bin_genomes, bin_genomes_maxbin2,
            assess_bins],
    description="Metagenome assembly + binning: fastp → MEGAHIT → MetaBAT2/MaxBin2 → CheckM2",
)
def metagenome_assembly(
    r1: Path,
    r2: Path,
    *,
    out_dir: Path,
    sample_id: str = "sample",
    binner: str = "metabat2",
    checkm2_db: Path = Path("/refs/checkm2"),
):
    """fastp → MEGAHIT → binning → CheckM2 end-to-end.

    ``binner`` selects the genome binner: ``"metabat2"`` (default; needs the
    minimap2 coverage BAM) or ``"maxbin2"`` (``--set binner=maxbin2``, which maps
    the reads itself).  Both emit ``bins/*.fa`` so CheckM2 downstream is
    unchanged.
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    clean = qc_trim(Path(r1), Path(r2))
    asm = assemble(clean)
    if binner == "maxbin2":
        bins = bin_genomes_maxbin2(asm, clean)
    else:
        mapped = map_back(asm, clean)
        bins = bin_genomes(mapped, asm)
    return assess_bins(bins, checkm2_db=Path(checkm2_db))


register("metagenome_assembly", metagenome_assembly)
