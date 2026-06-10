"""RNA-seq differential expression recipe.

End-to-end short-read RNA-seq DEG workflow:
    fastp (QC)  →  Salmon (alignment-free quant)  →  DESeq2 (DEG)

Inputs are a sample sheet (CSV) describing per-sample paired-end reads
and their condition labels, plus a reference transcriptome FASTA.

Sample sheet format::

    sample_id,fastq_r1,fastq_r2,condition
    s1,/data/s1_R1.fq.gz,/data/s1_R2.fq.gz,treated
    s2,/data/s2_R1.fq.gz,/data/s2_R2.fq.gz,treated
    s3,/data/s3_R1.fq.gz,/data/s3_R2.fq.gz,control
    s4,/data/s4_R1.fq.gz,/data/s4_R2.fq.gz,control

Researcher (Tier B) usage::

    bioflow recipe run rnaseq_deg \\
        --sample-sheet samples.csv --transcriptome ref.fa \\
        --out ./out

The clusterProfiler enrichment step is intentionally omitted from the
default chain because the existing tool YAML hardcodes
``org.Hs.eg.db`` (human only).  Run it separately if you have a human
DEG table.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Tuple

from bioflow import stage, pipeline
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="quay.io/biocontainers/fastp:0.23.4--h5f740d0_0",
       cpu=4, ram_gb=4)
def qc_one(sample_id: str, r1: Path, r2: Path, *, out_dir):
    """fastp QC for one paired-end sample."""
    return (
        f"fastp -i {r1} -I {r2} "
        f"-o {out_dir}/{sample_id}_R1.clean.fq.gz "
        f"-O {out_dir}/{sample_id}_R2.clean.fq.gz "
        f"--json {out_dir}/{sample_id}.fastp.json "
        f"--html {out_dir}/{sample_id}.fastp.html --thread 4"
    )


@stage(image="quay.io/biocontainers/salmon:1.10.3--h45fbf2d_5",
       cpu=8, ram_gb=16)
def salmon_index(transcriptome: Path, *, out_dir):
    """Build a Salmon index from a reference transcriptome FASTA."""
    return (
        f"salmon index -t {transcriptome} -i {out_dir}/index "
        f"--threads 8 -k 31"
    )


@stage(image="quay.io/biocontainers/salmon:1.10.3--h45fbf2d_5",
       cpu=8, ram_gb=16, depends_on=salmon_index)
def salmon_quant(idx, sample_id: str, r1_clean: Path, r2_clean: Path,
                 *, out_dir):
    """Salmon quant for one sample, against the prebuilt index."""
    return (
        f"salmon quant -i {idx.out_dir}/index -l A "
        f"-1 {r1_clean} -2 {r2_clean} "
        f"--threads 8 --validateMappings "
        f"-o {out_dir}/{sample_id}"
    )


@stage(image="quay.io/biocontainers/bioconductor-deseq2:1.44.0--r43hf17093f_0",
       cpu=4, ram_gb=16, depends_on=salmon_quant)
def deseq2_diff(quants, sample_sheet: Path, *, out_dir):
    """DESeq2 differential expression via tximport + DESeqDataSetFromTximport."""
    # All per-sample quant.sf files live under their per-sample out_dir
    quant_dirs = ",".join(str(q.out_dir) for q in quants)
    return (
        f"Rscript -e \""
        f"library(tximport); library(DESeq2); "
        f"samples <- read.csv('{sample_sheet}'); "
        f"quant_dirs <- strsplit('{quant_dirs}', ',')[[1]]; "
        f"files <- file.path(quant_dirs, samples$sample_id, 'quant.sf'); "
        f"names(files) <- samples$sample_id; "
        f"txi <- tximport(files, type='salmon', txOut=TRUE); "
        f"dds <- DESeqDataSetFromTximport(txi, colData=samples, design=~condition); "
        f"dds <- DESeq(dds); "
        f"res <- results(dds); "
        f"write.csv(as.data.frame(res), "
        f"          file='{out_dir}/deg_results.csv', quote=FALSE); "
        f"pdf('{out_dir}/ma_plot.pdf'); plotMA(res); dev.off()\""
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

def _parse_sample_sheet(path: Path) -> List[Tuple[str, Path, Path, str]]:
    """Return [(sample_id, r1, r2, condition), ...] from a CSV sample sheet."""
    rows: List[Tuple[str, Path, Path, str]] = []
    with open(path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        required = {"sample_id", "fastq_r1", "fastq_r2", "condition"}
        if not required.issubset(reader.fieldnames or []):
            missing = required - set(reader.fieldnames or [])
            raise ValueError(f"Sample sheet missing columns: {missing}")
        for r in reader:
            rows.append((
                r["sample_id"],
                Path(r["fastq_r1"]),
                Path(r["fastq_r2"]),
                r["condition"],
            ))
    if not rows:
        raise ValueError(f"Sample sheet {path} has no rows")
    return rows


@pipeline(
    stages=[qc_one, salmon_index, salmon_quant, deseq2_diff],
    description="RNA-seq DEG: fastp → Salmon → DESeq2",
)
def rnaseq_deg(
    sample_sheet: Path,
    transcriptome: Path,
    *,
    out_dir: Path,
):
    """End-to-end RNA-seq differential-expression analysis."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    samples = _parse_sample_sheet(Path(sample_sheet))

    # 1. fastp on every sample, in parallel.  `.starmap` unpacks each
    # tuple into the stage's positional args (sample_id, r1, r2).
    qc_results = qc_one.starmap(
        [(s_id, r1, r2) for s_id, r1, r2, _ in samples],
        parallel="auto", progress=True,
    )

    # 2. Build the Salmon index once
    idx = salmon_index(Path(transcriptome))

    # 3. Quant each sample against the index, in parallel
    clean_inputs = []
    for (s_id, _, _, _), qc in zip(samples, qc_results):
        clean_inputs.append((
            s_id,
            Path(qc.out_dir) / f"{s_id}_R1.clean.fq.gz",
            Path(qc.out_dir) / f"{s_id}_R2.clean.fq.gz",
        ))
    quant_results = salmon_quant.starmap(
        [(idx, s, r1, r2) for s, r1, r2 in clean_inputs],
        parallel="auto", progress=True,
    )

    # 4. DESeq2 on the assembled quants
    return deseq2_diff(quant_results, Path(sample_sheet))


register("rnaseq_deg", rnaseq_deg)
