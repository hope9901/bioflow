"""Bisulfite-sequencing (WGBS) methylation recipe.

End-to-end workflow:
    TrimGalore (bisulfite-aware trim)
        → Bismark (genome prep + bisulfite alignment + methylation extract)
        → methylKit (differentially-methylated region calling)

The ``--bismark-genome`` argument accepts **either**:

* a reference FASTA (``.fa`` / ``.fasta`` / ``.fna``), or a directory
  containing one — bioflow runs ``bismark_genome_preparation`` for you
  (the ``bismark_prep`` stage), so the recipe works from a plain
  reference; **or**
* an already-prepared Bismark genome directory (one that already holds a
  ``Bisulfite_Genome/`` subdirectory) — preparation is skipped and the
  index is used directly.

methylKit assumes a paired study design: treatment vs. control with a
matched-length list of CpG report files.  Pass --sample-ids /
--methylation-files / --treatment to drive it.

Researcher (Tier B) usage::

    bioflow recipe run methylation_wgbs \\
        --r1 sample_R1.fq.gz --r2 sample_R2.fq.gz \\
        --bismark-genome /refs/hg38.fa \\
        --sample-id sample01 --out ./out
"""
from __future__ import annotations

from pathlib import Path

from bioflow import stage, pipeline
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="quay.io/biocontainers/trim-galore:0.6.11--hdfd78af_0",
       cpu=4, ram_gb=8)
def trim(r1: Path, r2: Path, *, out_dir):
    """TrimGalore with --rrbs / standard adapter for bisulfite reads.

    The default flags here are for standard WGBS; for RRBS, add `--rrbs`
    to the command (see notes in docs/MAINTAINER.md if you want to
    parameterise this).
    """
    return f"trim_galore --paired --cores 4 --output_dir {out_dir} {r1} {r2}"


@stage(image="quay.io/biocontainers/bismark:0.25.1--hdfd78af_0",
       cpu=4, ram_gb=8)
def bismark_prep(genome: Path, aligner: str = "bowtie2", *, out_dir):
    """``bismark_genome_preparation`` — bisulfite-convert the reference.

    Copies the reference FASTA into a fresh, writable genome directory
    under the workspace and runs genome preparation there.  Bismark
    writes the ``Bisulfite_Genome/`` index *next to* the FASTA, so the
    FASTA must sit on a writable mount — an external, read-only
    ``--bismark-genome`` reference can't be prepared in place, hence the
    copy into ``out_dir`` (always under the ``/work`` mount).

    ``aligner`` picks the index Bismark builds: ``"bowtie2"`` (default) or
    ``"hisat2"`` (``--set aligner=hisat2``); the index must match the aligner
    used at the ``bismark_align`` step.  Both ship in this Bismark image.
    """
    flag = "--hisat2 " if aligner == "hisat2" else ""
    return (
        f"bash -c 'cp {genome} {out_dir}/ && "
        f"bismark_genome_preparation {flag}{out_dir}'"
    )


@stage(image="quay.io/biocontainers/bismark:0.25.1--hdfd78af_0",
       cpu=8, ram_gb=32, depends_on=(trim, bismark_prep),
       retry=2, retry_with={"ram_gb": "2x"})
def bismark_align(clean, bismark_genome: Path, sample_id: str,
                  aligner: str = "bowtie2", *, out_dir):
    """Bismark bisulfite alignment + methylation extractor.

    Trimmed-read filenames are resolved at runtime via ``ls | head -1``
    so the recipe survives variations in TrimGalore's naming.

    ``aligner`` selects Bismark's backend: ``"bowtie2"`` (default) or
    ``"hisat2"``.  Either way Bismark writes a ``*.bam`` + ``CpG_report`` that
    the extractor and methylKit read the same way, so downstream is unchanged.
    """
    flag = "--hisat2 " if aligner == "hisat2" else ""
    return (
        f"bash -c '"
        f"R1=$(ls {clean.out_dir}/*_val_1.fq.gz | head -1) && "
        f"R2=$(ls {clean.out_dir}/*_val_2.fq.gz | head -1) && "
        f"bismark {flag}--genome {bismark_genome} -1 \"$R1\" -2 \"$R2\" "
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
        # Match the CpG report (optionally .gz) with a [.] character class
        # for the literal dot — a backslash escape (\\.) would be eaten by
        # the shell before R sees it and trips R's "unrecognized escape".
        f"f <- list.files('{bismark.out_dir}/extracted', "
        f"pattern='CpG_report[.]txt', full.names=TRUE)[1]; "
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

def _resolve_genome_dir(bismark_genome: Path, aligner: str = "bowtie2") -> Path:
    """Return a prepared Bismark genome directory.

    * already-prepared dir (has ``Bisulfite_Genome/``) → use as-is, no
      preparation stage.
    * reference FASTA, or a dir containing one → run ``bismark_prep`` (for the
      chosen ``aligner``) and return its output dir.
    """
    bismark_genome = Path(bismark_genome)
    if (bismark_genome / "Bisulfite_Genome").is_dir():
        return bismark_genome  # already prepared — skip preparation

    if bismark_genome.is_dir():
        fastas = sorted(
            p for ext in ("*.fa", "*.fasta", "*.fna")
            for p in bismark_genome.glob(ext)
        )
        if not fastas:
            raise FileNotFoundError(
                f"--bismark-genome {bismark_genome} is a directory with no "
                f"FASTA (*.fa/*.fasta/*.fna) to prepare and no "
                f"Bisulfite_Genome/ index; pass a reference FASTA or a "
                f"pre-prepared Bismark genome directory."
            )
        genome_fa = fastas[0]
    else:
        genome_fa = bismark_genome  # a FASTA file

    return Path(bismark_prep(genome_fa, aligner).out_dir)


@pipeline(
    stages=[trim, bismark_prep, bismark_align, methylkit_dmr],
    description="WGBS methylation: TrimGalore → Bismark → methylKit",
)
def methylation_wgbs(
    r1: Path,
    r2: Path,
    bismark_genome: Path,
    *,
    out_dir: Path,
    sample_id: str = "sample",
    aligner: str = "bowtie2",
    genome_build: str = "hg38",
    context: str = "CpG",
):
    """End-to-end bisulfite alignment + methylation summary for one sample.

    ``aligner`` selects Bismark's alignment backend: ``"bowtie2"`` (default) or
    ``"hisat2"`` (``--set aligner=hisat2``).  Both ship in the Bismark image and
    write the same ``*.bam`` + CpG report, so methylKit downstream is unchanged.
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    clean = trim(Path(r1), Path(r2))
    genome_dir = _resolve_genome_dir(bismark_genome, aligner)
    bm = bismark_align(clean, genome_dir, sample_id, aligner)
    return methylkit_dmr(bm, sample_id,
                        genome_build=genome_build, context=context)


register("methylation_wgbs", methylation_wgbs)
