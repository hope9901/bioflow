"""Single-cell RNA-seq pipeline definition.

Stages (fixed order, per plan):
  step1  Demultiplex + alignment (Cell Ranger or STARsolo)
  step2  QC (filter cells, doublet detection)
  step3  Cluster + UMAP (Scanpy or Seurat)
  step4  Marker-gene detection
  step5  Trajectory inference (Monocle3; optional)
"""

from __future__ import annotations

PIPELINE_ID = "scrna_seq"

STAGES: list[dict] = [
    {
        "id": f"{PIPELINE_ID}.step1",
        "name": "Demultiplex + alignment",
        "inputs":  ["raw_reads", "star_index|cellranger_ref", "whitelist"],
        "outputs": ["count_matrix"],
    },
    {
        "id": f"{PIPELINE_ID}.step2",
        "name": "Cell QC",
        "inputs":  ["count_matrix"],
        "outputs": ["filtered_matrix", "qc_report"],
    },
    {
        "id": f"{PIPELINE_ID}.step3",
        "name": "Cluster + embed",
        "inputs":  ["filtered_matrix"],
        "outputs": ["clustered_h5ad", "umap_plot"],
    },
    {
        "id": f"{PIPELINE_ID}.step4",
        "name": "Marker genes",
        "inputs":  ["clustered_h5ad"],
        "outputs": ["marker_genes_tsv"],
    },
    {
        "id": f"{PIPELINE_ID}.step5",
        "name": "Trajectory inference",
        "inputs":  ["clustered_h5ad"],
        "outputs": ["trajectory_plot"],
    },
]
