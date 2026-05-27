"""Programmatic quick-start for the 8 per-pipeline recipes.

Demonstrates the SDK call pattern for each of the new pipeline-area
recipes added in 0.1.4.  Each block is independent — comment out the
ones you don't want to run.

All examples assume:
  * Docker is running and reachable
  * The container images will be pulled on first use
  * Input paths point to real data on your host (or under ``ws/``)

Researcher (Tier-B) users can run the same things via the CLI:

    bioflow recipe run prokaryote_assembly --r1 ... --r2 ... --out ./out

This file is the Tier-A (developer) equivalent — useful when you want to
chain multiple recipes, override defaults, or inspect StageResults
programmatically.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make this file runnable directly from a checkout (no install required)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bioflow import set_workspace
from bioflow.recipes import get

WS = Path(__file__).resolve().parent / "_recipes_quickstart_ws"
set_workspace(WS)
WS.mkdir(parents=True, exist_ok=True)


# ── 1 · Prokaryote de novo assembly ─────────────────────────────────────────
def run_prokaryote_assembly(r1: Path, r2: Path):
    """fastp → SPAdes → QUAST → Prokka."""
    return get("prokaryote_assembly")(
        r1=r1, r2=r2, out_dir=WS / "prok", sample_id="demo_strain",
    )


# ── 2 · RNA-seq DEG ─────────────────────────────────────────────────────────
def run_rnaseq_deg(sample_sheet: Path, transcriptome: Path):
    """fastp → Salmon (per-sample) → DESeq2 (with tximport bridge)."""
    return get("rnaseq_deg")(
        sample_sheet=sample_sheet,
        transcriptome=transcriptome,
        out_dir=WS / "rnaseq",
    )


# ── 3 · Metagenomic taxonomic profile ───────────────────────────────────────
def run_metagenomics(r1: Path, r2: Path, kraken2_db: Path):
    """fastp → Kraken2 → Bracken."""
    return get("metagenomics_profile")(
        r1=r1, r2=r2, kraken2_db=kraken2_db,
        out_dir=WS / "meta", sample_id="env_001",
    )


# ── 4 · 10x scRNA-seq ───────────────────────────────────────────────────────
def run_scrna_seq(r1: Path, r2: Path, star_index: Path, whitelist: Path):
    """STARsolo → Scanpy QC + cluster + UMAP."""
    return get("scrna_seq")(
        r1=r1, r2=r2, star_index=star_index, whitelist=whitelist,
        out_dir=WS / "scrna",
    )


# ── 5 · ChIP-seq ────────────────────────────────────────────────────────────
def run_chip_seq(r1: Path, r2: Path, bowtie2_index: Path,
                 reference: Path, annotation: Path):
    """TrimGalore → Bowtie2 → Picard MarkDuplicates → MACS3 → HOMER."""
    return get("chip_seq")(
        r1=r1, r2=r2, bowtie2_index=bowtie2_index,
        reference=reference, annotation=annotation,
        out_dir=WS / "chip", sample_id="chip_demo",
    )


# ── 6 · ATAC-seq ────────────────────────────────────────────────────────────
def run_atac_seq(r1: Path, r2: Path, bowtie2_index: Path, reference: Path):
    """TrimGalore → Bowtie2 -X 2000 → Picard → MACS3 (open-chrom) → TOBIAS."""
    return get("atac_seq")(
        r1=r1, r2=r2, bowtie2_index=bowtie2_index, reference=reference,
        out_dir=WS / "atac", sample_id="atac_demo",
    )


# ── 7 · WGBS methylation ────────────────────────────────────────────────────
def run_methylation(r1: Path, r2: Path, bismark_genome: Path):
    """TrimGalore → Bismark → methylKit (single-sample summary)."""
    return get("methylation_wgbs")(
        r1=r1, r2=r2, bismark_genome=bismark_genome,
        out_dir=WS / "meth", sample_id="meth_demo",
    )


# ── 8 · LC-MS/MS DDA proteomics ─────────────────────────────────────────────
def run_proteomics(raw_dir: Path, comet_params: Path, fasta_db: Path):
    """msconvert → Comet → Percolator (fully open-source stack)."""
    return get("proteomics_dda")(
        raw_dir=raw_dir,
        comet_params=comet_params,
        fasta_db=fasta_db,
        out_dir=WS / "prot",
    )


if __name__ == "__main__":
    # Print available recipes + example call signatures.  Substitute
    # real paths for a real run.
    from bioflow.recipes import names
    print("Available recipes:", sorted(names()))
    print(f"Workspace: {WS}")
    print("Edit this file to uncomment + supply inputs for any of the 8 "
          "per-pipeline recipes.")
