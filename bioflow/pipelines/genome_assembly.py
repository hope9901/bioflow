"""Genome Assembly & Annotation pipeline definition.

Stages (fixed order, per plan):
  step1  Read QC
  step2  Assembly (de novo short/HiFi/ONT/hybrid OR resequencing)
  step3  Assembly quality evaluation
  step4  Repeat masking
  step5  Structural annotation
  step6  Functional annotation

This module defines the canonical stage IDs and artifact contracts. Concrete
tool selection is resolved by the planner from the registry + user config.
"""

from __future__ import annotations

PIPELINE_ID = "genome_assembly"

STAGES: list[dict] = [
    {
        "id": f"{PIPELINE_ID}.step1",
        "name": "Read QC",
        "inputs":  ["raw_reads"],
        "outputs": ["clean_reads", "qc_report"],
    },
    {
        "id": f"{PIPELINE_ID}.step2",
        "name": "Assembly",
        "inputs":  ["clean_reads", "reference_genome?"],  # reference only for resequencing
        "outputs": ["assembly_fasta"],
    },
    {
        "id": f"{PIPELINE_ID}.step3",
        "name": "Assembly QC",
        "inputs":  ["assembly_fasta", "clean_reads?"],
        "outputs": ["assembly_qc_report"],
    },
    {
        "id": f"{PIPELINE_ID}.step4",
        "name": "Repeat masking",
        "inputs":  ["assembly_fasta"],
        "outputs": ["masked_assembly_fasta", "repeat_library"],
        "skippable_for": ["prokaryote"],
    },
    {
        "id": f"{PIPELINE_ID}.step5",
        "name": "Structural annotation",
        "inputs":  ["masked_assembly_fasta", "rnaseq_bam?"],  # optional evidence
        "outputs": ["structural_gff"],
    },
    {
        "id": f"{PIPELINE_ID}.step6",
        "name": "Functional annotation",
        "inputs":  ["structural_gff", "masked_assembly_fasta"],
        "outputs": ["functional_annotation_tsv"],
    },
]
