"""COG-2024 functional enrichment of a pangenome.

DIAMOND blastp every pangenome representative protein against a slim
COG-2024 reference, then aggregate the best-hit COG functional category
per pangenome bucket (core / soft_core / shell / cloud).

The two heavy operations — building the DIAMOND DB and running blastp —
are :class:`Stage` calls so they get cached.  The post-processing
(category mapping + bucket aggregation) is plain Python inside the
pipeline body.

Researcher (Tier B) usage::

    $ bioflow recipe run cog_enrichment \\
        --pangenome-faa rep_proteins.faa \\
        --cog-faa COG-2024-reps.faa \\
        --gpa-csv gene_presence_absence.csv \\
        --cog-def cog-24.def.tab
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from bioflow import stage, pipeline
from bioflow.io import write_text
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(
    image="quay.io/biocontainers/diamond:2.2.2--he361c42_0",
    cpu=4, ram_gb=4,
)
def diamond_makedb(reference_faa: Path, *, out_dir):
    """Build a DIAMOND protein DB from *reference_faa* (e.g. COG reps)."""
    return (
        f"sh -c 'diamond makedb --in {reference_faa} "
        f"-d {out_dir}/ref.dmnd'"
    )


@stage(
    image="quay.io/biocontainers/diamond:2.2.2--he361c42_0",
    cpu=8, ram_gb=8,
    depends_on=diamond_makedb,
)
def diamond_blastp(
    query_faa: Path, ref_db_dir: Path, *,
    out_dir,
    evalue: float = 1e-5,
):
    """Run DIAMOND blastp very-sensitive on *query_faa* vs the built DB."""
    return (
        f"sh -c 'diamond blastp --query {query_faa} "
        f"--db {ref_db_dir}/ref.dmnd "
        f"--out {out_dir}/hits.tsv "
        f"--outfmt 6 qseqid sseqid pident evalue bitscore "
        f"--very-sensitive -e {evalue} -p 8 --max-target-seqs 1 "
        f"--quiet'"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[diamond_makedb, diamond_blastp],
    description="Pangenome × COG-2024 functional-category enrichment",
)
def cog_enrichment(
    pangenome_faa: Path,
    cog_faa: Path,
    cog_def: Path,
    gpa_csv: Path,
    *,
    out_dir: Path,
    evalue: float = 1e-5,
):
    """COG-category enrichment of a Roary pangenome.

    Steps:
      1. Build a DIAMOND DB from *cog_faa* (COG-2024 reps recommended).
      2. blastp *pangenome_faa* (one rep per Roary cluster) against it.
      3. Map best-hit subject → COG → 1-letter functional category via
         *cog_def* (the NCBI cog-24.def.tab three-column file).
      4. Aggregate per Roary bucket (core / soft_core / shell / cloud)
         using the prevalence column of *gpa_csv*.

    Output files in *out_dir*:
      - ``hits.tsv``                  (raw DIAMOND output, from the stage)
      - ``cog_per_cluster.tsv``       (gene → COG → category)
      - ``cog_counts_by_bucket.tsv``  (counts matrix)
      - ``cog_fractions_by_bucket.tsv`` (column-normalised percentages)
    """
    import pandas as pd
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pangenome_faa = Path(pangenome_faa).resolve()
    cog_faa = Path(cog_faa).resolve()
    cog_def = Path(cog_def).resolve()
    gpa_csv = Path(gpa_csv).resolve()

    # ── 1. Build DIAMOND DB ───────────────────────────────────────────────
    db_result = diamond_makedb(cog_faa)

    # ── 2. blastp the pangenome representatives ──────────────────────────
    hit_result = diamond_blastp(pangenome_faa, db_result.out_dir, evalue=evalue)
    hits_path = hit_result.out_dir / "hits.tsv"
    if not hits_path.exists():
        return hit_result

    # ── 3. Map subject → COG → category (host-side, deterministic) ───────
    # cog-24.def.tab format: COG_id<TAB>categories<TAB>name<TAB>...
    cog_to_cats: dict = {}
    for line in cog_def.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].startswith("COG"):
            cog_to_cats[parts[0]] = list(parts[1])

    # DIAMOND subject IDs look like "<protein_id>|COGxxxx|..." — we
    # extract the first COGxxxx token.
    import re as _re
    cog_pat = _re.compile(r"(COG\d{4,})")

    cluster_to_cog: dict = {}
    with hits_path.open() as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            qid, sid = parts[0], parts[1]
            m = cog_pat.search(sid)
            if m:
                cluster_to_cog[qid] = m.group(1)

    # Per-cluster category letters (multi-letter assignments exploded)
    per_cluster_rows: list = []
    cluster_to_cats: dict = {}
    for qid, cog in cluster_to_cog.items():
        cats = cog_to_cats.get(cog, [])
        cluster_to_cats[qid] = cats
        per_cluster_rows.append(
            f"{qid}\t{cog}\t{''.join(cats)}"
        )
    write_text(
        out_dir / "cog_per_cluster.tsv",
        "cluster\tcog\tcategories\n" + "\n".join(per_cluster_rows) + "\n",
    )

    # ── 4. Bucket each pangenome cluster via the GPA "No. isolates" col ──
    gpa = pd.read_csv(gpa_csv, low_memory=False)
    n_strains = int(gpa["No. isolates"].max())

    def bucket_of(n: int) -> str:
        f = n / n_strains
        if f >= 0.99:
            return "core"
        if f >= 0.95:
            return "soft_core"
        if f >= 0.15:
            return "shell"
        return "cloud"

    # Counts: bucket × category
    counts: dict = defaultdict(Counter)
    for _, row in gpa[["Gene", "No. isolates"]].iterrows():
        b = bucket_of(int(row["No. isolates"]))
        cats = cluster_to_cats.get(row["Gene"], [])
        for c in cats:
            counts[b][c] += 1

    all_cats = sorted({c for b in counts.values() for c in b})
    buckets = ["core", "soft_core", "shell", "cloud"]

    header = "category\t" + "\t".join(buckets)
    rows = [header]
    for cat in all_cats:
        rows.append(
            cat + "\t" + "\t".join(
                str(counts[b].get(cat, 0)) for b in buckets
            )
        )
    write_text(out_dir / "cog_counts_by_bucket.tsv", "\n".join(rows) + "\n")

    # Fractions (column-normalised)
    bucket_totals = {
        b: max(sum(counts[b].values()), 1) for b in buckets
    }
    rows = [header]
    for cat in all_cats:
        rows.append(
            cat + "\t" + "\t".join(
                f"{100 * counts[b].get(cat, 0) / bucket_totals[b]:.2f}"
                for b in buckets
            )
        )
    write_text(out_dir / "cog_fractions_by_bucket.tsv", "\n".join(rows) + "\n")

    return hit_result


register("cog_enrichment", cog_enrichment)
