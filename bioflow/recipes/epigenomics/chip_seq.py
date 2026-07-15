"""ChIP-seq narrow peak-calling recipe.

End-to-end workflow:
    TrimGalore (adapter trim)
        → Bowtie2 (align to reference, sort + index BAM)
        → Picard MarkDuplicates (PCR-duplicate removal)
        → MACS3 callpeak (narrow peaks vs. input control)
        → HOMER annotatePeaks + findMotifsGenome (annotation + motifs)

Optional input/IgG control: pass ``--ctrl-bam`` pointing at a
pre-aligned, deduplicated control BAM; MACS3 receives it as ``-c``.
(Raw control reads are not aligned by this recipe — run the sample arm
on the control FASTQs separately, or use the BAM you already have.)

Researcher (Tier B) usage::

    bioflow recipe run chip_seq \\
        --r1 sample_R1.fq.gz --r2 sample_R2.fq.gz \\
        --bowtie2-index /refs/bowtie2/hg38 \\
        --reference /refs/hg38.fa --annotation /refs/hg38.gtf \\
        --genome-size hs --sample-id myChIP --out ./out
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from bioflow import stage, pipeline
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="quay.io/biocontainers/trim-galore:0.6.11--hdfd78af_0",
       cpu=4, ram_gb=8)
def trim(r1: Path, r2: Path, *, out_dir):
    """TrimGalore: paired-end adapter trim + Q20 filter."""
    return f"trim_galore --paired --cores 4 --output_dir {out_dir} {r1} {r2}"


@stage(image="staphb/bowtie2:2.5.5",
       cpu=8, ram_gb=16, depends_on=trim)
def align(clean, bowtie2_index: Path, sample_id: str, *, out_dir):
    """Bowtie2 alignment → sorted, indexed BAM.

    Uses the StaPH-B bowtie2 image, which bundles samtools (the plain
    ``biocontainers/bowtie2`` image does not, so the sort/index chain
    would fail there).  Trimmed-read filenames are resolved at runtime
    (``ls | head -1``) so the recipe survives TrimGalore's naming and
    never feeds a glob with multiple matches to ``bowtie2 -1``.
    """
    return (
        f"bash -c '"
        f"R1=$(ls {clean.out_dir}/*_val_1.fq.gz | head -1) && "
        f"R2=$(ls {clean.out_dir}/*_val_2.fq.gz | head -1) && "
        f"bowtie2 -x {bowtie2_index} -1 \"$R1\" -2 \"$R2\" "
        f"-S {out_dir}/{sample_id}.sam -p 8 2>{out_dir}/bowtie2.log && "
        f"samtools sort -@ 8 -o {out_dir}/{sample_id}.bam "
        f"{out_dir}/{sample_id}.sam && "
        f"samtools index {out_dir}/{sample_id}.bam && "
        f"rm {out_dir}/{sample_id}.sam'"
    )


@stage(image="quay.io/biocontainers/mulled-v2-fe8faa35dbf6dc65a0f7f5d4ea12e31a79f73e40:f45ad9036aa41bb10f875a330fa877d8869018a1-0",
       cpu=8, ram_gb=16, depends_on=trim)
def align_bwa(clean, bwa_index: Path, sample_id: str, *, out_dir):
    """BWA-MEM alignment → sorted, indexed BAM (``--set aligner=bwa``).

    Uses the bwa+samtools mulled BioContainer (plain ``bwa`` has no samtools).
    Writes the same ``{sample_id}.bam`` filename as the Bowtie2 stage, so
    Picard/MACS3 downstream are unchanged.  ``bwa_index`` is the reference
    FASTA prefix produced by ``bwa index``.
    """
    return (
        f"bash -c '"
        f"R1=$(ls {clean.out_dir}/*_val_1.fq.gz | head -1) && "
        f"R2=$(ls {clean.out_dir}/*_val_2.fq.gz | head -1) && "
        f"bwa mem -t 8 {bwa_index} \"$R1\" \"$R2\" 2>{out_dir}/bwa.log "
        f"| samtools sort -@ 8 -o {out_dir}/{sample_id}.bam - && "
        f"samtools index {out_dir}/{sample_id}.bam'"
    )


@stage(image="quay.io/biocontainers/picard:3.4.0--hdfd78af_0",
       cpu=4, ram_gb=16, depends_on=align)
def dedup(aln, sample_id: str, *, out_dir):
    """Picard MarkDuplicates: drop PCR / optical duplicates.

    ``CREATE_INDEX=true`` writes the ``.bai`` — the plain picard
    BioContainer ships no samtools, so calling ``samtools index`` here
    would fail.
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
def call_peaks(treat, sample_id: str, genome_size: str = "hs",
               *, out_dir, ctrl_bam: Optional[Path] = None):
    """MACS3 callpeak: narrow peaks for sharp TF / histone marks."""
    ctrl_arg = f"-c {ctrl_bam}" if ctrl_bam else ""
    return (
        f"macs3 callpeak -t {treat.out_dir}/{sample_id}.dedup.bam {ctrl_arg} "
        f"-f BAMPE -g {genome_size} -n {sample_id} "
        f"--outdir {out_dir} -B --SPMR 2>{out_dir}/macs3.log"
    )


@stage(image="quay.io/biocontainers/homer:5.1--pl5321hc52dbad_1",
       cpu=4, ram_gb=8, depends_on=call_peaks)
def annotate_peaks(peaks, reference: Path, annotation: Path, sample_id: str,
                   *, out_dir):
    """HOMER findMotifsGenome + annotatePeaks on the MACS3 narrowPeak file."""
    peaks_bed = f"{peaks.out_dir}/{sample_id}_peaks.narrowPeak"
    return (
        f"sh -c 'findMotifsGenome.pl {peaks_bed} {reference} "
        f"{out_dir}/motifs -size 200 -p 4 && "
        f"annotatePeaks.pl {peaks_bed} {reference} -gtf {annotation} "
        f"> {out_dir}/annotated_peaks.tsv'"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[trim, align, align_bwa, dedup, call_peaks, annotate_peaks],
    description="ChIP-seq: TrimGalore → Bowtie2/BWA → Picard → MACS3 → HOMER",
)
def chip_seq(
    r1: Path,
    r2: Path,
    bowtie2_index: Path,
    reference: Path,
    annotation: Path,
    *,
    out_dir: Path,
    sample_id: str = "sample",
    genome_size: str = "hs",
    aligner: str = "bowtie2",
    ctrl_bam: Optional[Path] = None,
):
    """End-to-end ChIP-seq narrow peak calling + motif annotation.

    ``aligner`` selects the read aligner: ``"bowtie2"`` (default, uses
    ``bowtie2_index``) or ``"bwa"`` (``--set aligner=bwa``, uses ``bowtie2_index``
    as the BWA reference-FASTA prefix — build it with ``bwa index``).  Both emit
    ``{sample_id}.bam`` so Picard/MACS3 downstream are unchanged.
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    clean = trim(Path(r1), Path(r2))
    if aligner == "bwa":
        aln = align_bwa(clean, Path(bowtie2_index), sample_id)
    else:
        aln = align(clean, Path(bowtie2_index), sample_id)
    dd = dedup(aln, sample_id)
    peaks = call_peaks(dd, sample_id, genome_size,
                       ctrl_bam=Path(ctrl_bam) if ctrl_bam else None)
    return annotate_peaks(peaks, Path(reference), Path(annotation), sample_id)


register("chip_seq", chip_seq)
