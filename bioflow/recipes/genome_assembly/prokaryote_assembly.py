"""Prokaryote de novo assembly + annotation recipe.

End-to-end short-read prokaryote workflow:
    fastp (QC)  →  SPAdes (de novo assembly)  →  QUAST (assembly QC)
                →  Prokka (structural annotation)

Researcher (Tier B) usage::

    bioflow recipe run prokaryote_assembly \\
        --r1 reads_R1.fastq.gz --r2 reads_R2.fastq.gz \\
        --sample-id ecoli_42 --out ./out

Programmatic (Tier A) usage::

    from bioflow.recipes import get
    pipe = get("prokaryote_assembly")
    pipe(r1=Path("R1.fq.gz"), r2=Path("R2.fq.gz"),
         sample_id="my_sample", out_dir=Path("./out"))
"""
from __future__ import annotations

from pathlib import Path

from bioflow import stage, pipeline
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="quay.io/biocontainers/fastp:0.23.4--h5f740d0_0",
       cpu=4, ram_gb=4)
def qc_trim(r1: Path, r2: Path, *, out_dir, min_qual: int = 15):
    """fastp: adapter trim + quality filter for paired-end short reads.

    ``min_qual`` is fastp's per-base quality threshold (its default, 15) —
    override per run with ``--set qc_trim.min_qual=30``.
    """
    return (
        f"fastp -i {r1} -I {r2} "
        f"-o {out_dir}/clean_R1.fastq.gz -O {out_dir}/clean_R2.fastq.gz "
        f"--qualified_quality_phred {min_qual} "
        f"--json {out_dir}/fastp.json --html {out_dir}/fastp.html "
        f"--thread 4"
    )


@stage(image="staphb/spades:4.0.0", cpu=8, ram_gb=16, depends_on=qc_trim,
       retry=2, retry_with={"ram_gb": "2x"})
def assemble(clean, *, out_dir, kmer: str = "auto"):
    """SPAdes de novo assembly from QC-cleaned reads.

    ``kmer`` is SPAdes' ``-k`` (default ``auto``) — override per run with
    ``--set assemble.kmer=21,33,55,77``.
    """
    return (
        f"spades.py "
        f"-1 {clean.out_dir}/clean_R1.fastq.gz "
        f"-2 {clean.out_dir}/clean_R2.fastq.gz "
        f"-k {kmer} "
        f"-o {out_dir} -t 8 -m 16 --only-assembler"
    )


@stage(image="staphb/quast:5.2.0", cpu=2, ram_gb=4, depends_on=assemble)
def assembly_qc(asm, *, out_dir):
    """QUAST: assembly contiguity & completeness metrics.

    Prefers ``scaffolds.fasta``; for very fragmented assemblies SPAdes
    can omit it, so we fall back to the always-present
    ``contigs.fasta``.
    """
    return (
        f"bash -c '"
        f"ASM={asm.out_dir}/scaffolds.fasta; "
        f"[ -f \"$ASM\" ] || ASM={asm.out_dir}/contigs.fasta; "
        f"quast.py -o {out_dir} -t 2 \"$ASM\"'"
    )


@stage(image="staphb/prokka:1.14.6", cpu=4, ram_gb=8, depends_on=assemble)
def annotate(asm, *, out_dir, sample_id: str = "sample"):
    """Prokka: structural annotation (CDS, rRNA, tRNA) on the assembly.

    Same scaffolds → contigs fall-back as ``assembly_qc``.
    """
    return (
        f"bash -c '"
        f"ASM={asm.out_dir}/scaffolds.fasta; "
        f"[ -f \"$ASM\" ] || ASM={asm.out_dir}/contigs.fasta; "
        f"prokka --outdir {out_dir}/prokka --prefix {sample_id} "
        f"--kingdom Bacteria --cpus 4 --force --fast \"$ASM\"'"
    )


@stage(image="staphb/bandage:0.8.1", cpu=2, ram_gb=4, depends_on=assemble)
def graph_image(asm, *, out_dir):
    """Bandage: render the SPAdes assembly graph to a PNG.

    Headless render needs Qt's offscreen platform (no X server in the
    container).  Prefers ``assembly_graph_with_scaffolds.gfa`` and falls back
    to the plain ``assembly_graph.gfa``.
    """
    return (
        f"bash -c 'export QT_QPA_PLATFORM=offscreen; "
        f"GFA={asm.out_dir}/assembly_graph_with_scaffolds.gfa; "
        f"[ -f \"$GFA\" ] || GFA={asm.out_dir}/assembly_graph.gfa; "
        f"Bandage image \"$GFA\" {out_dir}/assembly_graph.png'"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[qc_trim, assemble, assembly_qc, graph_image, annotate],
    description="Prokaryote short-read de novo assembly + Prokka annotation",
)
def prokaryote_assembly(
    r1: Path,
    r2: Path,
    *,
    out_dir: Path,
    sample_id: str = "sample",
):
    """fastp → SPAdes → QUAST + Bandage graph + Prokka end-to-end."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    clean = qc_trim(Path(r1), Path(r2))
    asm = assemble(clean)
    assembly_qc(asm)                # QUAST report lands in its own out_dir
    graph_image(asm)                # Bandage assembly-graph PNG
    return annotate(asm, sample_id=sample_id)


register("prokaryote_assembly", prokaryote_assembly)
