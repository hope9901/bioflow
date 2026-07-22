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
        f"--soloFeatures Gene "
        f"--soloCellFilter EmptyDrops_CR "
        f"--outSAMtype BAM SortedByCoordinate "
        f"--outFileNamePrefix {out_dir}/ "
        f"--soloOutFileNames Solo.out/ features.tsv barcodes.tsv matrix.mtx"
    )


@stage(image="quay.io/biocontainers/kb-python:0.28.2--pyhdfd78af_2",
       cpu=4, ram_gb=8)
def kb_ref(genome: Path, gtf: Path, *, out_dir):
    """kallisto|bustools index from a genome + GTF (``--set counter=kb``).

    ``kb ref`` builds its own kallisto index in-recipe, so — unlike STARsolo,
    which needs a prebuilt multi-GB STAR index — the kb path runs from a plain
    reference.  ``--tmp`` is required: ``kb`` otherwise makes a ``tmp/`` in the
    CWD and aborts if one exists.
    """
    return (
        f"kb ref --tmp {out_dir}/kbtmp "
        f"-i {out_dir}/index.idx -g {out_dir}/t2g.txt -f1 {out_dir}/cdna.fa "
        f"{genome} {gtf}"
    )


@stage(image="quay.io/biocontainers/kb-python:0.28.2--pyhdfd78af_2",
       cpu=8, ram_gb=16, depends_on=kb_ref,
       retry=2, retry_with={"ram_gb": "2x"})
def kb_count(r1: Path, r2: Path, kbref, whitelist: Path, *, out_dir,
             cb_len: int = 16, umi_len: int = 12):
    """kallisto|bustools count → a ``counts_unfiltered`` cells×genes matrix.

    The ``-x`` geometry is built from ``cb_len``/``umi_len`` (default 16+12 =
    10x v3): ``0,0,CB : 0,CB,CB+UMI : 1,0,0`` (barcode & UMI in R1, cDNA in R2).
    Scanpy reads the resulting ``cells_x_genes.mtx`` directly (already cells×
    genes), so ``scanpy_analyze`` handles it alongside STARsolo's matrix.
    """
    tech = f"0,0,{cb_len}:0,{cb_len},{cb_len + umi_len}:1,0,0"
    return (
        f"kb count --tmp {out_dir}/kbtmp "
        f"-i {kbref.out_dir}/index.idx -g {kbref.out_dir}/t2g.txt "
        f"-x {tech} -w {whitelist} -o {out_dir} {r1} {r2}"
    )


@stage(image="ghcr.io/hope9901/bioflow-scanpy:1.12.2",
       cpu=8, ram_gb=32, depends_on=starsolo)
def scanpy_analyze(solo, *, out_dir,
                   min_genes: int = 200, min_cells: int = 3):
    """Scanpy QC + normalize + cluster + UMAP from the count matrix.

    Reads whichever counter ran: STARsolo's ``Solo.out/Gene/filtered`` (falling
    back to ``raw``) via ``read_10x_mtx``, or kb-python's ``counts_unfiltered/
    cells_x_genes.mtx`` (already cells×genes) via ``read_mtx`` + the sidecar
    barcode/gene lists — so the Scanpy step is identical for both counters.

    The Scanpy logic is materialised to a sibling ``analyze.py`` rather
    than passed via ``python -c`` — that keeps the quoting sane and
    makes the script independently re-runnable for debugging.
    """
    script_path = Path(out_dir) / "analyze.py"
    script_path.write_text(
        "import sys, os\n"
        "import scanpy as sc\n"
        "mtx_dir = sys.argv[1]\n"
        "if os.path.exists(os.path.join(mtx_dir, 'cells_x_genes.mtx')):\n"
        "    import pandas as pd\n"
        "    adata = sc.read_mtx(os.path.join(mtx_dir, 'cells_x_genes.mtx'))\n"
        "    adata.obs_names = pd.read_csv(\n"
        "        os.path.join(mtx_dir, 'cells_x_genes.barcodes.txt'),\n"
        "        header=None)[0].astype(str).values\n"
        "    adata.var_names = pd.read_csv(\n"
        "        os.path.join(mtx_dir, 'cells_x_genes.genes.txt'),\n"
        "        header=None)[0].astype(str).values\n"
        "else:\n"
        "    adata = sc.read_10x_mtx(mtx_dir, var_names='gene_symbols')\n"
        f"sc.pp.filter_cells(adata, min_genes={min_genes})\n"
        f"sc.pp.filter_genes(adata, min_cells={min_cells})\n"
        "sc.pp.normalize_total(adata, target_sum=1e4)\n"
        "sc.pp.log1p(adata)\n"
        "sc.pp.highly_variable_genes(adata, n_top_genes=2000)\n"
        "sc.pp.scale(adata, max_value=10)\n"
        "sc.tl.pca(adata)\n"
        "sc.pp.neighbors(adata)\n"
        "sc.tl.umap(adata)\n"
        "sc.tl.leiden(adata)\n"
        "sc.tl.rank_genes_groups(adata, 'leiden', method='wilcoxon')\n"
        "adata.write(sys.argv[2])\n",
        encoding="utf-8",
    )
    filt = f"{solo.out_dir}/Solo.out/Gene/filtered"
    raw  = f"{solo.out_dir}/Solo.out/Gene/raw"
    kb   = f"{solo.out_dir}/counts_unfiltered"
    return (
        f"bash -c '"
        f"if [ -d {filt} ]; then MTX={filt}; "
        f"elif [ -d {kb} ]; then MTX={kb}; "
        f"else MTX={raw}; fi && "
        f"python {script_path} \"$MTX\" {out_dir}/analyzed.h5ad'"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[starsolo, kb_ref, kb_count, scanpy_analyze],
    description="scRNA-seq (10x): STARsolo/kb-python + Scanpy QC/cluster/UMAP",
)
def scrna_seq(
    r1: Path,
    r2: Path,
    whitelist: Path,
    *,
    out_dir: Path,
    counter: str = "starsolo",
    star_index: Path | None = None,
    genome: Path | None = None,
    gtf: Path | None = None,
    cb_len: int = 16,
    umi_len: int = 12,
    min_genes: int = 200,
    min_cells: int = 3,
):
    """STARsolo / kb-python → Scanpy single-cell analysis.

    ``counter`` selects the quantifier and its reference:
    ``"starsolo"`` (default) needs a prebuilt ``star_index``;
    ``"kb"`` (``--set counter=kb``) builds a kallisto index in-recipe from
    ``genome`` + ``gtf``.  Both feed the same Scanpy step, which reads whichever
    count matrix was written.
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if counter == "kb":
        if genome is None or gtf is None:
            raise ValueError("counter='kb' needs --genome and --gtf")
        kbref = kb_ref(Path(genome), Path(gtf))
        counts = kb_count(Path(r1), Path(r2), kbref, Path(whitelist),
                          cb_len=cb_len, umi_len=umi_len)
        return scanpy_analyze(counts, min_genes=min_genes, min_cells=min_cells)

    if star_index is None:
        raise ValueError("counter='starsolo' needs --star-index")
    solo = starsolo(Path(r1), Path(r2), Path(star_index), Path(whitelist),
                    cb_len=cb_len, umi_len=umi_len)
    return scanpy_analyze(solo, min_genes=min_genes, min_cells=min_cells)


register("scrna_seq", scrna_seq)
