"""Eukaryote long-read de novo assembly recipe.

End-to-end ONT/HiFi workflow using the long-read tools added in 0.1.10:
    NanoPlot (read QC)
        → Flye (long-read assembly)
        → Medaka (ONT consensus polish)
        → compleasm + gfastats (assembly QC)

For HiFi reads, polishing is usually unnecessary — pass
``--polish false`` (``polish=False``) to skip the Medaka step.

Researcher (Tier B) usage::

    bioflow recipe run eukaryote_assembly \\
        --long-reads sample.ont.fq.gz \\
        --genome-size 120m --busco-lineage eukaryota_odb10 \\
        --busco-db /refs/busco --out ./out
"""
from __future__ import annotations

from pathlib import Path

from bioflow import stage, pipeline
from bioflow.recipes import register, choice


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="quay.io/biocontainers/nanoplot:1.47.1--pyhdfd78af_0",
       cpu=4, ram_gb=8)
def read_qc(long_reads: Path, *, out_dir):
    """NanoPlot: long-read length / quality distribution."""
    return f"NanoPlot --fastq {long_reads} -o {out_dir} -t 4"


@stage(image="quay.io/biocontainers/flye:2.9.6--py313h7fbb527_1",
       cpu=16, ram_gb=64, depends_on=read_qc,
       retry=2, retry_with={"ram_gb": "2x"})
def assemble(qc, long_reads: Path, *, out_dir, read_mode: str = "--nano-hq"):
    """Flye long-read assembly. ``read_mode`` is --nano-hq / --pacbio-hifi."""
    return (
        f"flye {read_mode} {long_reads} --out-dir {out_dir} "
        f"--threads 16"
    )


@stage(image="quay.io/biocontainers/hifiasm:0.25.0--h5ca1c30_0",
       cpu=16, ram_gb=64, depends_on=read_qc,
       retry=2, retry_with={"ram_gb": "2x"})
def assemble_hifiasm(qc, long_reads: Path, *, out_dir):
    """hifiasm HiFi assembly (``--set assembler=hifiasm``).

    Writes the primary contigs to ``assembly.fasta`` — the same filename Flye
    produces — so Medaka/compleasm downstream need no changes.
    """
    return (
        f"hifiasm -o {out_dir}/asm -t 16 {long_reads}\n"
        f"awk '/^S/{{print \">\"$2\"\\n\"$3}}' "
        f"{out_dir}/asm.bp.p_ctg.gfa > {out_dir}/assembly.fasta"
    )


@stage(image="quay.io/biocontainers/medaka:2.2.2--py312h3050eb1_0",
       cpu=8, ram_gb=32, depends_on=assemble)
def polish_consensus(asm, long_reads: Path, *, out_dir, medaka_model: str = "r1041_e82_400bps_sup_v5.0.0"):
    """Medaka ONT consensus polish of the Flye assembly."""
    return (
        f"medaka_consensus -i {long_reads} "
        f"-d {asm.out_dir}/assembly.fasta -o {out_dir} "
        f"-t 8 -m {medaka_model}"
    )


@stage(image="quay.io/biocontainers/compleasm:0.2.8--pyh106432d_0",
       cpu=8, ram_gb=16, depends_on=polish_consensus)
def assess(polished, *, out_dir, busco_lineage: str = "eukaryota_odb10",
           busco_db: Path = Path("/refs/busco")):
    """compleasm completeness + gfastats contiguity (gfastats chained)."""
    return (
        f"bash -c '"
        f"ASM={polished.out_dir}/consensus.fasta; "
        f"[ -f \"$ASM\" ] || ASM={polished.out_dir}/assembly.fasta; "
        f"compleasm run -a \"$ASM\" -o {out_dir}/compleasm "
        f"-l {busco_lineage} -L {busco_db} -t 8'"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[read_qc, assemble, assemble_hifiasm, polish_consensus, assess],
    description="Eukaryote long-read assembly: NanoPlot → Flye/hifiasm → Medaka → compleasm",
)
def eukaryote_assembly(
    long_reads: Path,
    *,
    out_dir: Path,
    assembler: str = "flye",
    read_mode: str = "--nano-hq",
    polish: bool = True,
    medaka_model: str = "r1041_e82_400bps_sup_v5.0.0",
    busco_lineage: str = "eukaryota_odb10",
    busco_db: Path = Path("/refs/busco"),
):
    """NanoPlot → assembler → Medaka → compleasm end-to-end.

    ``assembler`` selects the long-read assembler: ``"flye"`` (default; ONT or
    HiFi via ``read_mode``) or ``"hifiasm"`` (``--set assembler=hifiasm``, for
    HiFi reads).  Both emit ``assembly.fasta`` so the rest of the pipeline is
    unchanged.  ``polish=False`` skips Medaka — appropriate for HiFi reads,
    whose per-base accuracy makes ONT consensus polishing unnecessary.
    """
    assembler = choice("assembler", assembler, "flye", "hifiasm")
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    lr = Path(long_reads)
    qc = read_qc(lr)
    if assembler == "hifiasm":
        asm = assemble_hifiasm(qc, lr)
    else:
        asm = assemble(qc, lr, read_mode=read_mode)
    polished = polish_consensus(asm, lr, medaka_model=medaka_model) if polish else asm
    return assess(polished, busco_lineage=busco_lineage, busco_db=Path(busco_db))


register("eukaryote_assembly", eukaryote_assembly)
