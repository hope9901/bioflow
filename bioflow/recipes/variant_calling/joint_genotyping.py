"""Cohort joint-genotyping recipe (GATK best practices).

Where ``germline_variants`` calls one sample straight to a VCF, real
cohort studies follow the GATK **joint-genotyping** workflow so that
evidence is shared across samples and a single multi-sample VCF is
produced:

    per sample:  fastp → BWA-MEM → MarkDuplicates
                 → HaplotypeCaller **-ERC GVCF**   (one g.vcf.gz each)
    cohort:      CombineGVCFs → GenotypeGVCFs
                 → hard-filter (best-practice SNP / INDEL filters)
                 → SnpEff

This is the canonical pattern reviewers expect for population / family
studies, and it exercises bioflow's fan-out (`.starmap`) for the
per-sample stages before converging on the joint steps.

Inputs
------
``sample_sheet``  CSV with columns ``sample_id,fastq_r1,fastq_r2``
``reference``     reference genome FASTA (indexed in-place if needed)
``snpeff_db``     SnpEff database name (e.g. ``GRCh38.105``)

Researcher (Tier B) usage::

    bioflow recipe run joint_genotyping \\
        --sample-sheet cohort.csv \\
        --reference /refs/genome.fa --snpeff-db Escherichia_coli_k12 \\
        --out ./cohort_out
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Tuple

from bioflow import pipeline, stage
from bioflow.recipes import register


# ── Per-sample stages (fan-out) ──────────────────────────────────────────────

@stage(image="quay.io/biocontainers/fastp:0.23.4--h5f740d0_0",
       cpu=4, ram_gb=4)
def qc_one(sample_id: str, r1: Path, r2: Path, *, out_dir):
    """fastp adapter trim + quality filter for one sample."""
    return (
        f"fastp -i {r1} -I {r2} "
        f"-o {out_dir}/{sample_id}_R1.clean.fq.gz "
        f"-O {out_dir}/{sample_id}_R2.clean.fq.gz "
        f"--json {out_dir}/{sample_id}.fastp.json "
        f"--html {out_dir}/{sample_id}.fastp.html --thread 4"
    )


@stage(image="quay.io/biocontainers/bwa:0.7.18--he4a0461_0",
       cpu=8, ram_gb=16, depends_on=qc_one)
def align_one(sample_id: str, clean, reference: Path, *, out_dir):
    """BWA-MEM → sorted, indexed BAM with a per-sample read group."""
    return (
        f"bash -c '"
        f"[ -f {reference}.bwt ] || bwa index {reference}; "
        f"bwa mem -t 8 -R \"@RG\\tID:{sample_id}\\tSM:{sample_id}\\tPL:ILLUMINA\" "
        f"{reference} "
        f"{clean.out_dir}/{sample_id}_R1.clean.fq.gz "
        f"{clean.out_dir}/{sample_id}_R2.clean.fq.gz "
        f"| samtools sort -@ 8 -o {out_dir}/{sample_id}.bam - && "
        f"samtools index {out_dir}/{sample_id}.bam'"
    )


@stage(image="quay.io/biocontainers/gatk4:4.6.1.0--py310hdfd78af_0",
       cpu=8, ram_gb=32, depends_on=align_one,
       retry=2, retry_with={"ram_gb": "2x"})
def call_gvcf(sample_id: str, aln, reference: Path, *, out_dir):
    """MarkDuplicates + HaplotypeCaller in GVCF mode (one g.vcf.gz)."""
    return (
        f"bash -c '"
        f"gatk MarkDuplicates -I {aln.out_dir}/{sample_id}.bam "
        f"-O {out_dir}/{sample_id}.dedup.bam -M {out_dir}/{sample_id}.dup.txt && "
        f"samtools index {out_dir}/{sample_id}.dedup.bam && "
        f"[ -f {reference}.fai ] || samtools faidx {reference}; "
        f"gatk CreateSequenceDictionary -R {reference} 2>/dev/null || true; "
        f"gatk HaplotypeCaller -R {reference} "
        f"-I {out_dir}/{sample_id}.dedup.bam "
        # Fixed output name so the converge step can reference each GVCF
        # without threading sample_ids — every sample has its own out_dir.
        f"-O {out_dir}/sample.g.vcf.gz "
        f"-ERC GVCF --native-pair-hmm-threads 8'"
    )


# ── Cohort stages (converge) ─────────────────────────────────────────────────

@stage(image="quay.io/biocontainers/gatk4:4.6.1.0--py310hdfd78af_0",
       cpu=4, ram_gb=16, depends_on=call_gvcf)
def combine_gvcfs(gvcfs, reference: Path, *, out_dir):
    """CombineGVCFs across every per-sample GVCF into one cohort GVCF."""
    v_args = " ".join(f"-V {g.out_dir}/sample.g.vcf.gz" for g in gvcfs)
    return (
        f"gatk CombineGVCFs -R {reference} {v_args} "
        f"-O {out_dir}/cohort.g.vcf.gz"
    )


@stage(image="quay.io/biocontainers/gatk4:4.6.1.0--py310hdfd78af_0",
       cpu=4, ram_gb=16, depends_on=combine_gvcfs)
def genotype_cohort(combined, reference: Path, *, out_dir):
    """GenotypeGVCFs → a single joint-genotyped multi-sample VCF."""
    return (
        f"gatk GenotypeGVCFs -R {reference} "
        f"-V {combined.out_dir}/cohort.g.vcf.gz "
        f"-O {out_dir}/cohort.vcf.gz"
    )


@stage(image="quay.io/biocontainers/gatk4:4.6.1.0--py310hdfd78af_0",
       cpu=4, ram_gb=16, depends_on=genotype_cohort)
def hard_filter(cohort, reference: Path, *, out_dir):
    """GATK best-practice hard filtering — SNPs and INDELs separately.

    VQSR needs truth resource bundles (HapMap / Omni / 1000G) that are
    organism-specific and multi-GB, so the recipe uses the documented
    hard-filter fallback, which is the recommended path for small
    cohorts and non-human organisms.
    """
    cohort_vcf = f"{cohort.out_dir}/cohort.vcf.gz"
    return (
        f"bash -c '"
        # --- SNPs ---
        f"gatk SelectVariants -R {reference} -V {cohort_vcf} "
        f"--select-type-to-include SNP -O {out_dir}/snps.vcf.gz && "
        f"gatk VariantFiltration -R {reference} -V {out_dir}/snps.vcf.gz "
        f"--filter-expression \"QD<2.0\" --filter-name QD2 "
        f"--filter-expression \"FS>60.0\" --filter-name FS60 "
        f"--filter-expression \"MQ<40.0\" --filter-name MQ40 "
        f"--filter-expression \"SOR>3.0\" --filter-name SOR3 "
        f"-O {out_dir}/snps.filtered.vcf.gz && "
        # --- INDELs ---
        f"gatk SelectVariants -R {reference} -V {cohort_vcf} "
        f"--select-type-to-include INDEL -O {out_dir}/indels.vcf.gz && "
        f"gatk VariantFiltration -R {reference} -V {out_dir}/indels.vcf.gz "
        f"--filter-expression \"QD<2.0\" --filter-name QD2 "
        f"--filter-expression \"FS>200.0\" --filter-name FS200 "
        f"--filter-expression \"SOR>10.0\" --filter-name SOR10 "
        f"-O {out_dir}/indels.filtered.vcf.gz && "
        # --- merge ---
        f"gatk MergeVcfs -I {out_dir}/snps.filtered.vcf.gz "
        f"-I {out_dir}/indels.filtered.vcf.gz "
        f"-O {out_dir}/cohort.filtered.vcf.gz'"
    )


@stage(image="quay.io/biocontainers/snpeff:5.2--hdfd78af_1",
       cpu=4, ram_gb=16, depends_on=hard_filter)
def annotate_cohort(filtered, snpeff_db: str, *, out_dir):
    """SnpEff functional annotation of the filtered cohort VCF."""
    return (
        f"bash -c '"
        f"snpEff -Xmx16g {snpeff_db} "
        f"{filtered.out_dir}/cohort.filtered.vcf.gz "
        f"> {out_dir}/cohort.annotated.vcf && "
        f"mv snpEff_genes.txt snpEff_summary.html {out_dir}/ 2>/dev/null || true'"
    )


# ── Sample sheet ─────────────────────────────────────────────────────────────

def _parse_sample_sheet(path: Path) -> List[Tuple[str, Path, Path]]:
    """Return [(sample_id, r1, r2), ...] from a CSV sample sheet."""
    rows: List[Tuple[str, Path, Path]] = []
    with open(path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        required = {"sample_id", "fastq_r1", "fastq_r2"}
        if not required.issubset(reader.fieldnames or []):
            missing = required - set(reader.fieldnames or [])
            raise ValueError(f"Sample sheet missing columns: {missing}")
        for r in reader:
            rows.append((r["sample_id"], Path(r["fastq_r1"]), Path(r["fastq_r2"])))
    if not rows:
        raise ValueError(f"Sample sheet {path} has no rows")
    return rows


# ── Pipeline ─────────────────────────────────────────────────────────────────

@pipeline(
    stages=[qc_one, align_one, call_gvcf, combine_gvcfs,
            genotype_cohort, hard_filter, annotate_cohort],
    description=(
        "Cohort joint genotyping (GATK best practice): "
        "per-sample GVCF → CombineGVCFs → GenotypeGVCFs → hard-filter → SnpEff"
    ),
)
def joint_genotyping(
    sample_sheet: Path,
    reference: Path,
    snpeff_db: str,
    *,
    out_dir: Path,
):
    """End-to-end multi-sample germline joint genotyping."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    reference = Path(reference)

    samples = _parse_sample_sheet(Path(sample_sheet))

    # 1. QC every sample in parallel.
    qc_results = qc_one.starmap(
        [(sid, r1, r2) for sid, r1, r2 in samples],
        parallel="auto", progress=True,
    )

    # 2. Align every sample in parallel.
    align_results = align_one.starmap(
        [(sid, qc, reference) for (sid, _, _), qc in zip(samples, qc_results)],
        parallel="auto", progress=True,
    )

    # 3. Per-sample GVCF in parallel.  Each writes sample.g.vcf.gz into
    #    its own out_dir, so the converge step needs no sample_id.
    gvcf_results = call_gvcf.starmap(
        [(sid, aln, reference)
         for (sid, _, _), aln in zip(samples, align_results)],
        parallel="auto", progress=True,
    )

    # 4. Converge: combine → joint genotype → hard filter → annotate.
    combined = combine_gvcfs(gvcf_results, reference)
    cohort = genotype_cohort(combined, reference)
    filt = hard_filter(cohort, reference)
    return annotate_cohort(filt, snpeff_db)


register("joint_genotyping", joint_genotyping)
