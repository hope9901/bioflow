"""ATAC-seq pipeline definition.

Stages (fixed order, per plan):
  step1  Read QC (TrimGalore)
  step2  Alignment (Bowtie2 -X 2000 + samtools, Picard MarkDuplicates)
  step3  Peak calling (MACS3 --nomodel --shift -75 --extsize 150)
  step4  Coverage / QC (deepTools, fragment-size distribution)
  step5  Footprinting (TOBIAS ATACorrect + ScoreBigwig)
"""

from __future__ import annotations

PIPELINE_ID = "atac_seq"

STAGES: list[dict] = [
    {
        "id": f"{PIPELINE_ID}.step1",
        "name": "Read QC + adapter trim",
        "inputs":  ["raw_reads"],
        "outputs": ["clean_reads", "qc_report"],
    },
    {
        "id": f"{PIPELINE_ID}.step2",
        "name": "Alignment + dedup",
        "inputs":  ["clean_reads", "bowtie2_index"],
        "outputs": ["alignment_bam", "dedup_metrics"],
    },
    {
        "id": f"{PIPELINE_ID}.step3",
        "name": "Peak calling (open chromatin)",
        "inputs":  ["alignment_bam"],
        "outputs": ["peaks_bed"],
    },
    {
        "id": f"{PIPELINE_ID}.step4",
        "name": "Coverage / fragment QC",
        "inputs":  ["alignment_bam"],
        "outputs": ["bigwig", "fragment_size_plot"],
    },
    {
        "id": f"{PIPELINE_ID}.step5",
        "name": "TF footprinting",
        "inputs":  ["alignment_bam", "peaks_bed", "reference_genome"],
        "outputs": ["footprint_bigwig"],
    },
]
