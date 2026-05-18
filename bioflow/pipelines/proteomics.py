"""LC-MS/MS proteomics pipeline definition.

Stages (fixed order, per plan):
  step1  Vendor → mzML conversion (msconvert)
  step2  Database search (MSFragger; standalone or via FragPipe)
  step3  FDR control (Percolator)
  step4  Quantification + protein assembly (IonQuant + Philosopher,
         typically wrapped by FragPipe)
  step5  Statistics + reporting (MSstats; optional)
"""

from __future__ import annotations

PIPELINE_ID = "proteomics"

STAGES: list[dict] = [
    {
        "id": f"{PIPELINE_ID}.step1",
        "name": "Vendor → mzML conversion",
        "inputs":  ["ms_raw"],
        "outputs": ["mzml"],
    },
    {
        "id": f"{PIPELINE_ID}.step2",
        "name": "Database search",
        "inputs":  ["mzml", "protein_fasta"],
        "outputs": ["pep_xml", "psm_results"],
    },
    {
        "id": f"{PIPELINE_ID}.step3",
        "name": "FDR control",
        "inputs":  ["pep_xml"],
        "outputs": ["validated_psms"],
    },
    {
        "id": f"{PIPELINE_ID}.step4",
        "name": "Quantification + protein assembly",
        "inputs":  ["validated_psms", "mzml"],
        "outputs": ["protein_abundance", "peptide_abundance"],
    },
    {
        "id": f"{PIPELINE_ID}.step5",
        "name": "Statistics + reporting",
        "inputs":  ["protein_abundance", "metadata_csv"],
        "outputs": ["statistics_report"],
    },
]
