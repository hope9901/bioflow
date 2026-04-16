"""RNA-seq DEG pipeline definition.

Stages (fixed order, per plan):
  step1  RNA-seq QC
  step2  Genome alignment or alignment-free quantification
  step3  DEG analysis (DESeq2 / edgeR / limma-voom)
  step4  GO / KEGG / GSEA enrichment

Concrete tool selection is resolved by the planner from the registry.
Requires a sample sheet (CSV: sample_id, fastq_r1, fastq_r2, condition, batch).
"""

from __future__ import annotations

PIPELINE_ID = "rnaseq_deg"

STAGES: list[dict] = [
    {
        "id": f"{PIPELINE_ID}.step1",
        "name": "RNA-seq QC",
        "inputs":  ["raw_reads", "sample_sheet"],
        "outputs": ["clean_reads", "qc_report"],
    },
    {
        "id": f"{PIPELINE_ID}.step2",
        "name": "Alignment / Quantification",
        "inputs":  ["clean_reads", "reference_genome", "annotation_gtf"],
        "outputs": ["count_matrix", "alignment_bam?"],
    },
    {
        "id": f"{PIPELINE_ID}.step3",
        "name": "DEG analysis",
        "inputs":  ["count_matrix", "sample_sheet"],
        "outputs": ["deg_table", "deg_plots"],
    },
    {
        "id": f"{PIPELINE_ID}.step4",
        "name": "Enrichment (GO / KEGG / GSEA)",
        "inputs":  ["deg_table", "annotation_gtf"],
        "outputs": ["enrichment_report"],
    },
]
