"""Bisulfite-sequencing (WGBS / RRBS) methylation pipeline definition.

Stages (fixed order, per plan):
  step1  Read QC + bisulfite-aware trim (TrimGalore --rrbs?)
  step2  Bisulfite alignment (Bismark)
  step3  Methylation extraction + CpG report (bismark_methylation_extractor)
  step4  Differentially-methylated region calling (methylKit)
"""

from __future__ import annotations

PIPELINE_ID = "methylation"

STAGES: list[dict] = [
    {
        "id": f"{PIPELINE_ID}.step1",
        "name": "Read QC + bisulfite trim",
        "inputs":  ["raw_reads"],
        "outputs": ["clean_reads", "qc_report"],
    },
    {
        "id": f"{PIPELINE_ID}.step2",
        "name": "Bisulfite alignment",
        "inputs":  ["clean_reads", "bismark_genome"],
        "outputs": ["alignment_bam"],
    },
    {
        "id": f"{PIPELINE_ID}.step3",
        "name": "Methylation extraction",
        "inputs":  ["alignment_bam", "bismark_genome"],
        "outputs": ["cytosine_report", "methylation_report"],
    },
    {
        "id": f"{PIPELINE_ID}.step4",
        "name": "DMR calling",
        "inputs":  ["cytosine_report"],
        "outputs": ["dmr_results", "methylation_plots"],
    },
]
