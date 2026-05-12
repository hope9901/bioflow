"""Single-cell RNA-seq recipe (10x Chromium, license-free path).

End-to-end workflow:
    STARsolo (alignment + UMI count matrix)
        → Scanpy (QC, normalize, cluster, UMAP, marker genes)

Cell Ranger is intentionally avoided — it ships a non-free EULA on the
Docker image.  STARsolo is the standard free alternative and produces
the same Matrix-Market output that Scanpy reads.

Inputs are a pair of 10x FASTQs (R1 contains cell barcode + UMI; R2
contains the cDNA read), a prebuilt STAR genome index, and a 10x
barcode whitelist (gzipped or plain).

Researcher (Tier B) usage::

    bioflow recipe run scrna_seq \\
        --r1 sample_S1_L001_R1_001.fastq.gz \\
        --r2 sample_S1_L001_R2_001.fastq.gz \\
        --star-index /refs/star/human \\
        --whitelist /refs/10x/3M-february-2018.txt \\
        --out ./out
"""
from __future__ import annotations

from pathlib import Path

from bioflow import stage, pipeline
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="quay.io/biocontainers/star:2.7.11b--h43eeafb_0",
       cpu=16, ram_gb=64, retry=2, retry_with={"ram_gb": "2x"})
def starsolo(r1: Path, r2: Path, star_index: Path, whitelist: Path,
             *, out_dir,
             cb_len: int = 16, umi_len: int = 12):
    """STARsolo: align 10x reads and emit a UMI-aware count matrix."""
    return (
        f"STAR --runMode alignReads --runThreadN 16 "
        f"--genomeDir {star_index} "
        f"--readFilesIn {r2} {r1} "
        f"--readFilesCommand zcat "
        f"--soloType CB_UMI_Simple "
        f"--soloCBwhitelist {whitelist} "
        f"--soloCBstart 1 --soloCBlen {cb_len} "
        f"--soloUMIstart {cb_len + 1} --soloUMIlen {umi_len} "
        f"--outSAMtype BAM SortedByCoordinate "
        f"--outFileNamePrefix {out_dir}/ "
        f"--soloOutFileNames Solo.out/ features.tsv barcodes.tsv matrix.mtx"
    )


@stage(image="quay.io/biocontainers/scanpy:1.10.1--pyhdfd78af_0",
       cpu=8, ram_gb=32, depends_on=starsolo)
def scanpy_analyze(solo, *, out_dir,
                   min_genes: int = 200, min_cells: int = 3):
    """Scanpy QC + normalize + cluster + UMAP from the STARsolo matrix."""
    mtx_dir = f"{solo.out_dir}/Solo.out/Gene/filtered"
    return (
        f"python -c \""
        f"import scanpy as sc; "
        f"adata = sc.read_10x_mtx('{mtx_dir}', var_names='gene_symbols'); "
        f"sc.pp.filter_cells(adata, min_genes={min_genes}); "
        f"sc.pp.filter_genes(adata, min_cells={min_cells}); "
        f"sc.pp.normalize_total(adata, target_sum=1e4); "
        f"sc.pp.log1p(adata); "
        f"sc.pp.highly_variable_genes(adata, n_top_genes=2000); "
        f"sc.pp.scale(adata, max_value=10); "
        f"sc.tl.pca(adata); "
        f"sc.pp.neighbors(adata); "
        f"sc.tl.umap(adata); "
        f"sc.tl.leiden(adata); "
        f"sc.tl.rank_genes_groups(adata, 'leiden', method='wilcoxon'); "
        f"adata.write('{out_dir}/analyzed.h5ad')\""
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[starsolo, scanpy_analyze],
    description="scRNA-seq (10x): STARsolo + Scanpy QC/cluster/UMAP",
)
def scrna_seq(
    r1: Path,
    r2: Path,
    star_index: Path,
    whitelist: Path,
    *,
    out_dir: Path,
    cb_len: int = 16,
    umi_len: int = 12,
    min_genes: int = 200,
    min_cells: int = 3,
):
    """STARsolo → Scanpy single-cell analysis."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    solo = starsolo(Path(r1), Path(r2), Path(star_index), Path(whitelist),
                    cb_len=cb_len, umi_len=umi_len)
    return scanpy_analyze(solo, min_genes=min_genes, min_cells=min_cells)


register("scrna_seq", scrna_seq)
