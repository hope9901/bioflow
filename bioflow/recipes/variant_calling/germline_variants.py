"""Germline short-variant calling recipe.

End-to-end short-read resequencing → variant workflow:
    fastp (QC)
        → BWA-MEM (align) + samtools sort/index
        → GATK MarkDuplicates + HaplotypeCaller (SNP/indel calling)
        → bcftools filter (quality cut)
        → SnpEff (functional annotation)

Inputs:
    r1, r2          paired-end short reads
    reference       reference genome FASTA (must be BWA-indexed; the
                    recipe builds the index if absent)
    snpeff_db       SnpEff database name for the organism (e.g.
                    ``GRCh38.105``, ``Escherichia_coli_k12``)

Researcher (Tier B) usage::

    bioflow recipe run germline_variants \\
        --r1 sample_R1.fq.gz --r2 sample_R2.fq.gz \\
        --reference /refs/genome.fa --snpeff-db Escherichia_coli_k12 \\
        --sample-id sample01 --out ./out
"""
from __future__ import annotations

from pathlib import Path

from bioflow import stage, pipeline
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="quay.io/biocontainers/fastp:0.23.4--h5f740d0_0",
       cpu=4, ram_gb=4)
def qc_trim(r1: Path, r2: Path, *, out_dir):
    """fastp adapter trim + quality filter."""
    return (
        f"fastp -i {r1} -I {r2} "
        f"-o {out_dir}/clean_R1.fq.gz -O {out_dir}/clean_R2.fq.gz "
        f"--json {out_dir}/fastp.json --html {out_dir}/fastp.html --thread 4"
    )


@stage(image="quay.io/biocontainers/bwa:0.7.18--he4a0461_0",
       cpu=8, ram_gb=16, depends_on=qc_trim)
def align(clean, reference: Path, sample_id: str, *, out_dir):
    """BWA-MEM alignment → sorted, indexed BAM with read-group.

    Builds the BWA index in-place if the reference hasn't been indexed.
    samtools is bundled in the BWA BioContainer.
    """
    return (
        f"bash -c '"
        f"[ -f {reference}.bwt ] || bwa index {reference}; "
        f"bwa mem -t 8 -R \"@RG\\tID:{sample_id}\\tSM:{sample_id}\\tPL:ILLUMINA\" "
        f"{reference} {clean.out_dir}/clean_R1.fq.gz {clean.out_dir}/clean_R2.fq.gz "
        f"| samtools sort -@ 8 -o {out_dir}/{sample_id}.bam - && "
        f"samtools index {out_dir}/{sample_id}.bam'"
    )


@stage(image="quay.io/biocontainers/gatk4:4.6.1.0--py310hdfd78af_0",
       cpu=8, ram_gb=32, depends_on=align,
       retry=2, retry_with={"ram_gb": "2x"})
def call_variants(aln, reference: Path, sample_id: str, *, out_dir):
    """GATK MarkDuplicates + HaplotypeCaller.

    Requires a reference .dict and .fai; builds both if missing.
    """
    return (
        f"bash -c '"
        f"gatk MarkDuplicates -I {aln.out_dir}/{sample_id}.bam "
        f"-O {out_dir}/{sample_id}.dedup.bam -M {out_dir}/dup_metrics.txt && "
        f"samtools index {out_dir}/{sample_id}.dedup.bam && "
        f"[ -f {reference}.fai ] || samtools faidx {reference}; "
        f"gatk CreateSequenceDictionary -R {reference} 2>/dev/null || true; "
        f"gatk HaplotypeCaller -R {reference} "
        f"-I {out_dir}/{sample_id}.dedup.bam "
        f"-O {out_dir}/{sample_id}.raw.vcf.gz "
        f"--native-pair-hmm-threads 8'"
    )


@stage(image="quay.io/biocontainers/bcftools:1.21--h8b25389_0",
       cpu=4, ram_gb=8, depends_on=call_variants)
def filter_variants(vcf, sample_id: str, *, out_dir,
                    min_qual: int = 30, min_depth: int = 10):
    """bcftools quality / depth filtering."""
    return (
        f"bash -c '"
        f"bcftools filter -e \"QUAL<{min_qual} || INFO/DP<{min_depth}\" "
        f"-Oz -o {out_dir}/{sample_id}.filtered.vcf.gz "
        f"{vcf.out_dir}/{sample_id}.raw.vcf.gz && "
        f"bcftools index {out_dir}/{sample_id}.filtered.vcf.gz'"
    )


@stage(image="quay.io/biocontainers/snpeff:5.2--hdfd78af_1",
       cpu=4, ram_gb=16, depends_on=filter_variants)
def annotate_variants(filtered, snpeff_db: str, sample_id: str, *, out_dir):
    """SnpEff functional annotation of the filtered VCF."""
    return (
        f"bash -c '"
        f"snpEff -Xmx16g {snpeff_db} "
        f"{filtered.out_dir}/{sample_id}.filtered.vcf.gz "
        f"> {out_dir}/{sample_id}.annotated.vcf && "
        f"mv snpEff_genes.txt snpEff_summary.html {out_dir}/ 2>/dev/null || true'"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[qc_trim, align, call_variants, filter_variants, annotate_variants],
    description="Germline variants: fastp → BWA → GATK → bcftools → SnpEff",
)
def germline_variants(
    r1: Path,
    r2: Path,
    reference: Path,
    snpeff_db: str,
    *,
    out_dir: Path,
    sample_id: str = "sample",
    min_qual: int = 30,
    min_depth: int = 10,
):
    """End-to-end germline SNP/indel calling + annotation."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    clean = qc_trim(Path(r1), Path(r2))
    aln = align(clean, Path(reference), sample_id)
    raw = call_variants(aln, Path(reference), sample_id)
    filt = filter_variants(raw, sample_id, min_qual=min_qual, min_depth=min_depth)
    return annotate_variants(filt, snpeff_db, sample_id)


register("germline_variants", germline_variants)
