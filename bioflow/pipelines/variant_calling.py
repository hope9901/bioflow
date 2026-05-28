"""Germline variant-calling pipeline definition.

Stages (fixed order, per plan):
  step1  Read QC + adapter trim (fastp / TrimGalore)
  step2  Alignment + variant calling (BWA → GATK HaplotypeCaller /
         bcftools / FreeBayes)
  step3  Variant filtering (bcftools / GATK VariantFiltration)
  step4  Variant annotation (SnpEff)

Tool selection is resolved by the planner from the registry.
"""

from __future__ import annotations

PIPELINE_ID = "variant_calling"

STAGES: list[dict] = [
    {
        "id": f"{PIPELINE_ID}.step1",
        "name": "Read QC + adapter trim",
        "inputs":  ["raw_reads"],
        "outputs": ["clean_reads", "qc_report"],
    },
    {
        "id": f"{PIPELINE_ID}.step2",
        "name": "Alignment + variant calling",
        "inputs":  ["clean_reads", "reference_fasta", "bwa_index"],
        "outputs": ["alignment_bam", "vcf"],
    },
    {
        "id": f"{PIPELINE_ID}.step3",
        "name": "Variant filtering",
        "inputs":  ["vcf"],
        "outputs": ["filtered_vcf"],
    },
    {
        "id": f"{PIPELINE_ID}.step4",
        "name": "Variant annotation",
        "inputs":  ["filtered_vcf", "snpeff_db"],
        "outputs": ["annotated_vcf", "variant_report"],
    },
]
