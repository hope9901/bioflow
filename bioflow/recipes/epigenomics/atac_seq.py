"""ATAC-seq accessibility + footprinting recipe.

End-to-end workflow:
    TrimGalore (adapter trim)
        → Bowtie2 (align to reference, sort + index BAM)
        → Picard MarkDuplicates (PCR-duplicate removal)
        → MACS3 callpeak (--nomodel --shift -75 --extsize 150, ATAC-style)
        → TOBIAS ATACorrect + ScoreBigwig (TF footprint signal)

Same skeleton as the ChIP-seq recipe but the peak-caller flags target
open-chromatin signal, and TOBIAS replaces HOMER at the end so we get
TF footprinting bigwigs.  Control BAMs are not used in ATAC.

Researcher (Tier B) usage::

    bioflow recipe run atac_seq \\
        --r1 sample_R1.fq.gz --r2 sample_R2.fq.gz \\
        --bowtie2-index /refs/bowtie2/hg38 \\
        --reference /refs/hg38.fa \\
        --genome-size hs --sample-id myATAC --out ./out
"""
from __future__ import annotations

from pathlib import Path

from bioflow import stage, pipeline
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="quay.io/biocontainers/trim-galore:0.6.11--hdfd78af_0",
       cpu=4, ram_gb=8)
def trim(r1: Path, r2: Path, *, out_dir):
    """TrimGalore: adapter trim + Q20 filter."""
    return f"trim_galore --paired --cores 4 --output_dir {out_dir} {r1} {r2}"


@stage(image="staphb/bowtie2:2.5.5",
       cpu=8, ram_gb=16, depends_on=trim)
def align(clean, bowtie2_index: Path, sample_id: str, *, out_dir):
    """Bowtie2 align with -X 2000 (ATAC-seq fragment max), sort + index.

    Uses the StaPH-B bowtie2 image, which bundles samtools (the plain
    ``biocontainers/bowtie2`` image does not).  Trimmed-read filenames
    are resolved at runtime via ``ls | head -1`` so the recipe is robust
    to TrimGalore's naming conventions.
    """
    return (
        f"bash -c '"
        f"R1=$(ls {clean.out_dir}/*_val_1.fq.gz | head -1) && "
        f"R2=$(ls {clean.out_dir}/*_val_2.fq.gz | head -1) && "
        f"bowtie2 -x {bowtie2_index} -1 \"$R1\" -2 \"$R2\" "
        f"-X 2000 --very-sensitive "
        f"-S {out_dir}/{sample_id}.sam -p 8 2>{out_dir}/bowtie2.log && "
        f"samtools sort -@ 8 -o {out_dir}/{sample_id}.bam "
        f"{out_dir}/{sample_id}.sam && "
        f"samtools index {out_dir}/{sample_id}.bam && "
        f"rm {out_dir}/{sample_id}.sam'"
    )


@stage(image="quay.io/biocontainers/picard:3.4.0--hdfd78af_0",
       cpu=4, ram_gb=16, depends_on=align)
def dedup(aln, sample_id: str, *, out_dir):
    """Picard MarkDuplicates: drop PCR / optical duplicates.

    ``CREATE_INDEX=true`` writes the ``.bai`` (TOBIAS needs an indexed
    BAM); the plain picard BioContainer has no samtools, so a
    ``samtools index`` call would fail here.
    """
    return (
        f"picard MarkDuplicates "
        f"I={aln.out_dir}/{sample_id}.bam "
        f"O={out_dir}/{sample_id}.dedup.bam "
        f"M={out_dir}/{sample_id}.dup_metrics.txt "
        f"REMOVE_DUPLICATES=true CREATE_INDEX=true"
    )


@stage(image="quay.io/biocontainers/macs3:3.0.4--py310h5a5e57a_0",
       cpu=4, ram_gb=8, depends_on=dedup)
def call_peaks(dd, sample_id: str, genome_size: str = "hs", *, out_dir):
    """MACS3 callpeak in ATAC mode (open-chromatin signal)."""
    return (
        f"macs3 callpeak -t {dd.out_dir}/{sample_id}.dedup.bam "
        f"-f BAMPE -g {genome_size} -n {sample_id} "
        f"--nomodel --shift -75 --extsize 150 -B --SPMR "
        f"--outdir {out_dir} 2>{out_dir}/macs3.log"
    )


@stage(image="quay.io/biocontainers/tobias:0.17.3--py39hff726c5_1",
       cpu=8, ram_gb=16, depends_on=call_peaks)
def footprint(peaks, dd, reference: Path, sample_id: str, *, out_dir):
    """TOBIAS ATACorrect + ScoreBigwig: TF footprint bigwig."""
    peaks_bed = f"{peaks.out_dir}/{sample_id}_peaks.narrowPeak"
    bam = f"{dd.out_dir}/{sample_id}.dedup.bam"
    return (
        f"sh -c 'TOBIAS ATACorrect --bam {bam} --genome {reference} "
        f"--peaks {peaks_bed} --outdir {out_dir} --cores 8 && "
        f"TOBIAS ScoreBigwig "
        f"--signal {out_dir}/{sample_id}.dedup_corrected.bw "
        f"--regions {peaks_bed} "
        f"--output {out_dir}/footprints.bw --cores 8'"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[trim, align, dedup, call_peaks, footprint],
    description="ATAC-seq: TrimGalore → Bowtie2 → Picard → MACS3 → TOBIAS",
)
def atac_seq(
    r1: Path,
    r2: Path,
    bowtie2_index: Path,
    reference: Path,
    *,
    out_dir: Path,
    sample_id: str = "sample",
    genome_size: str = "hs",
):
    """End-to-end ATAC-seq open-chromatin + TF-footprinting analysis."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    clean = trim(Path(r1), Path(r2))
    aln = align(clean, Path(bowtie2_index), sample_id)
    dd = dedup(aln, sample_id)
    peaks = call_peaks(dd, sample_id, genome_size)
    return footprint(peaks, dd, Path(reference), sample_id)


register("atac_seq", atac_seq)
