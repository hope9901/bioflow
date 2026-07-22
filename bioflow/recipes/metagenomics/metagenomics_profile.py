"""Metagenomic taxonomic profiling recipe.

End-to-end short-read shotgun-metagenomic workflow:
    fastp (QC)  →  Kraken2 (taxonomic classify)  →  Bracken (abundance estimate)

Requires a prebuilt Kraken2 database mounted into the workspace (e.g.
the standard MiniKraken2 or PlusPF DB).  Use::

    bioflow db fetch kraken2_standard_8gb --dest /refs

…to install one, or pass --kraken2-db pointing to a pre-existing
directory.  (Bracken also needs the ``databaseNNmers.kmer_distrib``
files that ship inside the standard Kraken2 DB tarball.)

Researcher (Tier B) usage::

    bioflow recipe run metagenomics_profile \\
        --r1 sample_R1.fastq.gz --r2 sample_R2.fastq.gz \\
        --kraken2-db /refs/kraken2_standard --sample-id sample \\
        --out ./out
"""
from __future__ import annotations

from pathlib import Path

from bioflow import stage, pipeline
from bioflow.recipes import register, choice


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="quay.io/biocontainers/fastp:1.3.6--h43da1c4_0",
       cpu=4, ram_gb=4)
def qc_trim(r1: Path, r2: Path, *, out_dir):
    """fastp QC + adapter trim."""
    return (
        f"fastp -i {r1} -I {r2} "
        f"-o {out_dir}/clean_R1.fq.gz -O {out_dir}/clean_R2.fq.gz "
        f"--json {out_dir}/fastp.json --html {out_dir}/fastp.html "
        f"--thread 4"
    )


@stage(image="quay.io/biocontainers/kraken2:2.1.6--pl5321h077b44d_0",
       cpu=8, ram_gb=32, depends_on=qc_trim,
       retry=2, retry_with={"ram_gb": "2x"})
def kraken2_classify(clean, kraken2_db: Path, sample_id: str, *, out_dir):
    """Kraken2 taxonomic classification of metagenomic reads."""
    return (
        f"kraken2 --db {kraken2_db} --paired --threads 8 "
        f"--output {out_dir}/{sample_id}.kraken.out "
        f"--report {out_dir}/{sample_id}.kraken.report "
        f"{clean.out_dir}/clean_R1.fq.gz {clean.out_dir}/clean_R2.fq.gz"
    )


@stage(image="quay.io/biocontainers/bracken:3.1--h9948957_0",
       cpu=2, ram_gb=8, depends_on=kraken2_classify)
def bracken_abundance(k2, kraken2_db: Path, sample_id: str,
                      *, out_dir, read_length: int = 150,
                      level: str = "S", threshold: int = 10):
    """Bracken species-level abundance refinement from a Kraken2 report."""
    return (
        f"bracken -d {kraken2_db} "
        f"-i {k2.out_dir}/{sample_id}.kraken.report "
        f"-o {out_dir}/{sample_id}.bracken.tsv "
        f"-r {read_length} -l {level} -t {threshold}"
    )


@stage(image="quay.io/biocontainers/metaphlan:4.2.4--pyhdfd78af_0",
       cpu=8, ram_gb=32, depends_on=qc_trim)
def metaphlan_profile(clean, sample_id: str, *, out_dir, metaphlan_db: str = ""):
    """MetaPhlAn4 marker-gene taxonomic profile (``--set profiler=metaphlan``).

    A single-step alternative to Kraken2+Bracken.  Needs the MetaPhlAn DB
    (``--set metaphlan_profile.metaphlan_db=/refs/metaphlan``).  Writes
    ``{sample_id}.metaphlan.tsv``, which ``krona_chart`` reshapes in place of
    the Bracken table.
    """
    # MetaPhlAn 4.2 renamed --bowtie2db to --db_dir (the old flag is now
    # rejected as an unrecognized argument).
    db = f"--db_dir {metaphlan_db}" if metaphlan_db else ""
    return (
        f"metaphlan {clean.out_dir}/clean_R1.fq.gz,{clean.out_dir}/clean_R2.fq.gz "
        f"--input_type fastq --nproc 8 {db} "
        f"-o {out_dir}/{sample_id}.metaphlan.tsv "
        f"--bowtie2out {out_dir}/{sample_id}.bowtie2.bz2"
    )


@stage(image="staphb/krona:2.8.1", cpu=2, ram_gb=4, depends_on=bracken_abundance)
def krona_chart(prof, sample_id: str, *, out_dir):
    """Krona: interactive taxonomic sunburst from whichever profiler ran.

    Reshapes into Krona's ``<value>\\t<label>`` text: Bracken's TSV
    (``new_est_reads`` col 6, taxon col 1) when present, else MetaPhlAn's
    species rows (relative abundance col 3, the ``s__`` clade name).  No
    taxonomy DB needed; ``ktImportText`` writes a self-contained HTML.
    """
    bracken = f"{prof.out_dir}/{sample_id}.bracken.tsv"
    metaphlan = f"{prof.out_dir}/{sample_id}.metaphlan.tsv"
    return (
        f"bash -c 'B={bracken}; M={metaphlan}; K={out_dir}/krona.txt; "
        f"if [ -f \"$B\" ]; then "
        f"tail -n +2 \"$B\" | cut -f6 > {out_dir}/val.tmp; "
        f"tail -n +2 \"$B\" | cut -f1 > {out_dir}/name.tmp; "
        f"paste {out_dir}/val.tmp {out_dir}/name.tmp > \"$K\"; "
        f"else "
        f"grep \"s__\" \"$M\" | grep -v \"t__\" | "
        f"awk -F\"\\t\" \"{{c=\\$1; sub(/.*[|]/, \\\"\\\", c); print \\$3 \\\"\\t\\\" c}}\" > \"$K\"; "
        f"fi; "
        f"ktImportText \"$K\" -o {out_dir}/krona.html'"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[qc_trim, kraken2_classify, bracken_abundance,
            metaphlan_profile, krona_chart],
    description="Shotgun metagenomic profiling: fastp → Kraken2+Bracken|MetaPhlAn → Krona",
)
def metagenomics_profile(
    r1: Path,
    r2: Path,
    kraken2_db: Path = Path(""),
    *,
    out_dir: Path,
    sample_id: str = "sample",
    profiler: str = "kraken2",
    metaphlan_db: str = "",
    read_length: int = 150,
    level: str = "S",
    threshold: int = 10,
):
    """fastp → taxonomic profiler → Krona end-to-end taxonomic profile.

    ``profiler`` selects the classifier: ``"kraken2"`` (default; Kraken2 + Bracken,
    needs ``kraken2_db``) or ``"metaphlan"`` (``--set profiler=metaphlan``, a
    single-step marker-gene profiler needing ``metaphlan_db``).  Krona reads
    whichever ran.
    """
    profiler = choice("profiler", profiler, "kraken2", "metaphlan")
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    clean = qc_trim(Path(r1), Path(r2))
    if profiler == "metaphlan":
        prof = metaphlan_profile(clean, sample_id, metaphlan_db=metaphlan_db)
    else:
        k2 = kraken2_classify(clean, Path(kraken2_db), sample_id)
        prof = bracken_abundance(
            k2, Path(kraken2_db), sample_id,
            read_length=read_length, level=level, threshold=threshold,
        )
    krona_chart(prof, sample_id)      # interactive Krona sunburst
    return prof


register("metagenomics_profile", metagenomics_profile)
