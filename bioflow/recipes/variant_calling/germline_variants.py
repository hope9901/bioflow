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

# The bwa+samtools mulled BioContainer (bwa 0.7.19 + samtools 1.22.1).  The
# plain ``quay.io/biocontainers/bwa`` image carries bwa only, so any
# ``bwa mem | samtools sort`` chain fails there.  Spelled out as a literal in
# each ``@stage`` below (not via this constant) so the recipe↔registry
# alignment guard — which only sees literal image strings — actually checks it
# against the ``bwa_samtools`` registry entry.


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="quay.io/biocontainers/fastp:1.3.6--h43da1c4_0",
       cpu=4, ram_gb=4)
def qc_trim(r1: Path, r2: Path, *, out_dir):
    """fastp adapter trim + quality filter."""
    return (
        f"fastp -i {r1} -I {r2} "
        f"-o {out_dir}/clean_R1.fq.gz -O {out_dir}/clean_R2.fq.gz "
        f"--json {out_dir}/fastp.json --html {out_dir}/fastp.html --thread 4"
    )


@stage(image="quay.io/biocontainers/mulled-v2-fe8faa35dbf6dc65a0f7f5d4ea12e31a79f73e40:f45ad9036aa41bb10f875a330fa877d8869018a1-0",
       cpu=4, ram_gb=8)
def prepare_reference(reference: Path, *, out_dir):
    """Build the BWA index + ``.fai`` + sequence ``.dict``, once.

    GATK needs all three next to the reference, and the per-sample
    ``align`` / ``call_variants`` stages would otherwise each have to
    build them — wasteful here, and an outright race in the cohort
    recipe's fan-out.  Doing it once up front (and writing the
    side-effect index files next to the reference, on its read-write
    mount) lets the gatk-image call stage stay samtools-free.
    """
    return (
        f"bash -c '"
        f"REF={reference}; "
        f"[ -f \"$REF\".bwt ] || bwa index \"$REF\"; "
        f"[ -f \"$REF\".fai ] || samtools faidx \"$REF\"; "
        f"DICT=\"${{REF%.*}}.dict\"; "
        f"[ -f \"$DICT\" ] || samtools dict \"$REF\" -o \"$DICT\"'"
    )


@stage(image="quay.io/biocontainers/mulled-v2-fe8faa35dbf6dc65a0f7f5d4ea12e31a79f73e40:f45ad9036aa41bb10f875a330fa877d8869018a1-0",
       cpu=8, ram_gb=16, depends_on=(qc_trim, prepare_reference))
def align(clean, reference: Path, sample_id: str, *, out_dir):
    """BWA-MEM alignment → sorted, indexed BAM with read-group.

    The reference is already indexed by :func:`prepare_reference`; this
    mulled image carries both bwa and samtools so the sort/index chain
    works.
    """
    return (
        f"bash -c '"
        f"bwa mem -t 8 -R \"@RG\\tID:{sample_id}\\tSM:{sample_id}\\tPL:ILLUMINA\" "
        f"{reference} {clean.out_dir}/clean_R1.fq.gz {clean.out_dir}/clean_R2.fq.gz "
        f"| samtools sort -@ 8 -o {out_dir}/{sample_id}.bam - && "
        f"samtools index {out_dir}/{sample_id}.bam'"
    )


@stage(image="quay.io/biocontainers/gatk4:4.6.2.0--py310hdfd78af_1",
       cpu=8, ram_gb=32, depends_on=align,
       retry=2, retry_with={"ram_gb": "2x"})
def call_variants(aln, reference: Path, sample_id: str, *, out_dir):
    """GATK MarkDuplicates + HaplotypeCaller.

    The reference ``.fai`` / ``.dict`` come from
    :func:`prepare_reference`, and ``MarkDuplicates --CREATE_INDEX``
    writes the dedup BAM's index — so this stage needs only gatk (the
    gatk4 image ships no samtools).
    """
    return (
        f"bash -c '"
        f"gatk MarkDuplicates -I {aln.out_dir}/{sample_id}.bam "
        f"-O {out_dir}/{sample_id}.dedup.bam -M {out_dir}/dup_metrics.txt "
        f"--CREATE_INDEX true && "
        f"gatk HaplotypeCaller -R {reference} "
        f"-I {out_dir}/{sample_id}.dedup.bam "
        f"-O {out_dir}/{sample_id}.raw.vcf.gz "
        f"--native-pair-hmm-threads 8'"
    )


@stage(image="google/deepvariant:1.10.0",
       cpu=8, ram_gb=32, depends_on=align,
       retry=2, retry_with={"ram_gb": "2x"})
def call_variants_deepvariant(aln, reference: Path, sample_id: str, *, out_dir,
                              model_type: str = "WGS"):
    """DeepVariant calling (``--set caller=deepvariant``).

    Writes the same ``{sample_id}.raw.vcf.gz`` the GATK stage produces, so
    bcftools/SnpEff downstream are unchanged.  Unlike the GATK path this does
    not MarkDuplicates first — DeepVariant's model is trained on
    duplicate-containing reads; pre-mark them yourself if your protocol needs
    it.  ``model_type`` is WGS / WES / PACBIO / ONT_R104.
    """
    return (
        f"/opt/deepvariant/bin/run_deepvariant "
        f"--model_type={model_type} --ref={reference} "
        f"--reads={aln.out_dir}/{sample_id}.bam "
        f"--output_vcf={out_dir}/{sample_id}.raw.vcf.gz "
        f"--num_shards=8"
    )


@stage(image="quay.io/biocontainers/bcftools:1.23.1--hb2cee57_0",
       cpu=4, ram_gb=8, depends_on=call_variants)
def filter_variants(vcf, sample_id: str, *, out_dir,
                    min_qual: int = 30, min_depth: int = 10):
    """bcftools quality / depth filtering, whichever caller produced the VCF.

    GATK HaplotypeCaller records depth in ``INFO/DP``; DeepVariant only emits a
    per-sample ``FORMAT/DP``.  Referencing a tag the VCF lacks makes bcftools
    abort ("No such INFO field: DP"), so pick the field from the header instead
    of hard-coding one caller's layout.
    """
    raw = f"{vcf.out_dir}/{sample_id}.raw.vcf.gz"
    return (
        f"bash -c '"
        f"RAW={raw}; "
        f"if bcftools view -h \"$RAW\" | grep -q \"^##INFO=<ID=DP,\"; "
        f"then DPF=INFO/DP; else DPF=FORMAT/DP; fi; "
        f"bcftools filter -e \"QUAL<{min_qual} || $DPF<{min_depth}\" "
        f"-Oz -o {out_dir}/{sample_id}.filtered.vcf.gz \"$RAW\" && "
        f"bcftools index {out_dir}/{sample_id}.filtered.vcf.gz'"
    )


@stage(image="quay.io/biocontainers/snpeff:5.4.0c--hdfd78af_0",
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
    stages=[qc_trim, prepare_reference, align, call_variants,
            call_variants_deepvariant, filter_variants, annotate_variants],
    description="Germline variants: fastp → BWA → GATK/DeepVariant → bcftools → SnpEff",
)
def germline_variants(
    r1: Path,
    r2: Path,
    reference: Path,
    snpeff_db: str,
    *,
    out_dir: Path,
    sample_id: str = "sample",
    caller: str = "gatk4",
    min_qual: int = 30,
    min_depth: int = 10,
):
    """End-to-end germline SNP/indel calling + annotation.

    ``caller`` selects the variant caller: ``"gatk4"`` (default; MarkDuplicates
    + HaplotypeCaller) or ``"deepvariant"`` (``--set caller=deepvariant``).
    Both write ``{sample_id}.raw.vcf.gz``, so bcftools/SnpEff are unchanged.
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    reference = Path(reference)

    clean = qc_trim(Path(r1), Path(r2))
    prepare_reference(reference)            # index + .fai + .dict, once
    aln = align(clean, reference, sample_id)
    if caller == "deepvariant":
        raw = call_variants_deepvariant(aln, reference, sample_id)
    else:
        raw = call_variants(aln, reference, sample_id)
    filt = filter_variants(raw, sample_id, min_qual=min_qual, min_depth=min_depth)
    return annotate_variants(filt, snpeff_db, sample_id)


register("germline_variants", germline_variants)
