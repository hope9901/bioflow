"""ChIP-seq pipeline definition.

Stages (fixed order, per plan):
  step1  Read QC (TrimGalore / fastp)
  step2  Alignment (Bowtie2 + samtools sort/index, Picard MarkDuplicates)
  step3  Peak calling (MACS3 narrow / broad)
  step4  Coverage / QC (deepTools, plotFingerprint, computeMatrix)
  step5  Annotation + motifs (HOMER annotatePeaks / findMotifsGenome)

Tool selection is resolved by the planner from the registry; presets
under ``registry/presets/`` pick a default chain for each scenario.
"""

from __future__ import annotations

PIPELINE_ID = "chip_seq"

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
        "name": "Peak calling",
        "inputs":  ["alignment_bam", "control_bam?"],
        "outputs": ["peaks_bed"],
    },
    {
        "id": f"{PIPELINE_ID}.step4",
        "name": "Coverage / QC",
        "inputs":  ["alignment_bam"],
        "outputs": ["bigwig", "qc_plots"],
    },
    {
        "id": f"{PIPELINE_ID}.step5",
        "name": "Annotation + motifs",
        "inputs":  ["peaks_bed", "reference_genome", "annotation_gtf"],
        "outputs": ["annotated_peaks", "motif_results"],
    },
]
