"""Metagenomics pipeline definition.

Stages (fixed order, per plan):
  step1  Read QC (fastp)
  step2  Host-read removal (KneadData; optional)
  step3  Taxonomic profiling (Kraken2 + Bracken, or MetaPhlAn4)
  step4  Functional profiling (HUMAnN3; optional)
  step5  Differential abundance (LEfSe; optional)
"""

from __future__ import annotations

PIPELINE_ID = "metagenomics"

STAGES: list[dict] = [
    {
        "id": f"{PIPELINE_ID}.step1",
        "name": "Read QC + adapter trim",
        "inputs":  ["raw_reads"],
        "outputs": ["clean_reads", "qc_report"],
    },
    {
        "id": f"{PIPELINE_ID}.step2",
        "name": "Host-read removal",
        "inputs":  ["clean_reads", "host_db"],
        "outputs": ["nonhost_reads"],
    },
    {
        "id": f"{PIPELINE_ID}.step3",
        "name": "Taxonomic profiling",
        "inputs":  ["nonhost_reads", "kraken2_db|metaphlan_db"],
        "outputs": ["taxonomy_report", "abundance_tsv"],
    },
    {
        "id": f"{PIPELINE_ID}.step4",
        "name": "Functional profiling",
        "inputs":  ["nonhost_reads", "humann_db"],
        "outputs": ["pathway_abundance", "gene_family_abundance"],
    },
    {
        "id": f"{PIPELINE_ID}.step5",
        "name": "Differential abundance",
        "inputs":  ["abundance_tsv", "metadata_csv"],
        "outputs": ["lefse_results"],
    },
]
