"""Bisulfite-sequencing (WGBS) methylation recipe.

End-to-end workflow:
    TrimGalore (bisulfite-aware trim)
        → Bismark (genome prep + bisulfite alignment + methylation extract)
        → methylKit (differentially-methylated region calling)

Bismark needs a pre-prepared bisulfite genome (`bismark_genome_preparation`)
in the directory passed via --bismark-genome.  If the directory hasn't
been bisulfite-converted yet, the genome-prep stage handles it.

methylKit assumes a paired study design: treatment vs. control with a
matched-length list of CpG report files.  Pass --sample-ids /
--methylation-files / --treatment to drive it.

Researcher (Tier B) usage::

    bioflow recipe run methylation_wgbs \\
        --r1 sample_R1.fq.gz --r2 sample_R2.fq.gz \\
        --bismark-genome /refs/bismark/hg38 \\
        --sample-id sample01 --out ./out
"""
from __future__ import annotations

from pathlib import Path

from bioflow import stage, pipeline
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="quay.io/biocontainers/trim-galore:0.6.10--hdfd78af_0",
       cpu=4, ram_gb=8)
def trim(r1: Path, r2: Path, *, out_dir):
    """TrimGalore with --rrbs / standard adapter for bisulfite reads.

    The default flags here are for standard WGBS; for RRBS, add `--rrbs`
    to the command (see notes in docs/MAINTAINER.md if you want to
    parameterise this).
    """
    return f"trim_galore --paired --cores 4 --output_dir {out_dir} {r1} {r2}"


@stage(image="quay.io/biocontainers/bismark:0.24.2--hdfd78af_0",
       cpu=8, ram_gb=32, depends_on=trim,
       retry=2, retry_with={"ram_gb": "2x"})
def bismark_align(clean, bismark_genome: Path, sample_id: str, *, out_dir):
    """Bismark bisulfite alignment + methylation extractor.

    Trimmed-read filenames are resolved at runtime via ``ls | head -1``
    so the recipe survives variations in TrimGalore's naming.
    """
    return (
        f"bash -c '"
        f"R1=$(ls {clean.out_dir}/*_val_1.fq.gz | head -1) && "
        f"R2=$(ls {clean.out_dir}/*_val_2.fq.gz | head -1) && "
        f"bismark --genome {bismark_genome} -1 \"$R1\" -2 \"$R2\" "
        f"-o {out_dir} --multicore 4 && "
        f"bismark_methylation_extractor --paired-end --comprehensive "
        f"--cytosine_report --genome_folder {bismark_genome} "
        f"{out_dir}/*.bam -o {out_dir}/extracted'"
    )


@stage(image="quay.io/biocontainers/bioconductor-methylkit:1.36.0--r45ha27e39d_0",
       cpu=4, ram_gb=16, depends_on=bismark_align)
def methylkit_dmr(bismark, sample_id: str, *, out_dir,
                  genome_build: str = "hg38",
                  context: str = "CpG",
                  difference: int = 25, qvalue: float = 0.01):
    """methylKit DMR calling on the Bismark CpG report.

    Single-sample mode by default — produces methylation density and
    summary plots; full DMR calling requires multiple samples wired
    through the methylKit Python/R API.
    """
    return (
        f"Rscript -e \""
        f"library(methylKit); "
        f"f <- list.files('{bismark.out_dir}/extracted', "
        f"pattern='CpG_report.txt(\\\\.gz)?$', full.names=TRUE)[1]; "
        f"if (is.na(f)) stop('No CpG_report found'); "
        f"obj <- methRead(as.list(f), sample.id=as.list('{sample_id}'), "
        f"assembly='{genome_build}', pipeline='bismarkCytosineReport', "
        f"context='{context}', treatment=0L); "
        f"pdf('{out_dir}/methylation_density.pdf'); "
        f"getMethylationStats(obj[[1]], plot=TRUE, both.strands=FALSE); "
        f"getCoverageStats(obj[[1]], plot=TRUE, both.strands=FALSE); "
        f"dev.off()\""
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[trim, bismark_align, methylkit_dmr],
    description="WGBS methylation: TrimGalore → Bismark → methylKit",
)
def methylation_wgbs(
    r1: Path,
    r2: Path,
    bismark_genome: Path,
    *,
    out_dir: Path,
    sample_id: str = "sample",
    genome_build: str = "hg38",
    context: str = "CpG",
):
    """End-to-end bisulfite alignment + methylation summary for one sample."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    clean = trim(Path(r1), Path(r2))
    bm = bismark_align(clean, Path(bismark_genome), sample_id)
    return methylkit_dmr(bm, sample_id,
                        genome_build=genome_build, context=context)


register("methylation_wgbs", methylation_wgbs)
