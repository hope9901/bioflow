"""Extract one representative protein sequence per Roary gene cluster.

Roary's clustered_proteins file lists, per cluster, every locus_tag in
every member strain.  We pick the first locus_tag and grab its translated
sequence from the corresponding Prokka .faa.

Output:
  pangenome_reps.faa     -- 34,629 sequences, one per cluster
  pangenome_reps.tsv     -- cluster_id, rep_locus_tag, bucket (core/cloud/...)
"""
from __future__ import annotations
import sys, re
from pathlib import Path
from collections import defaultdict

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = ROOT / "analysis" / "dickeya"
PROKKA   = ANALYSIS / "prokka_full"
ROARY    = ANALYSIS / "roary_full" / "out"
OUT_DIR  = ANALYSIS / "eggnog"; OUT_DIR.mkdir(exist_ok=True)

# 1. Parse clustered_proteins → cluster -> first locus_tag
print("Reading Roary clustered_proteins …")
cluster_to_rep: dict[str, str] = {}
n_member: dict[str, int] = {}
with (ROARY / "clustered_proteins").open(encoding="utf-8") as fh:
    for line in fh:
        cluster, _, members = line.rstrip().partition(": ")
        if not members: continue
        m = members.split("\t")
        cluster_to_rep[cluster] = m[0]   # first locus_tag = representative
        n_member[cluster] = len(m)
print(f"  {len(cluster_to_rep)} clusters")

# 2. Get gene_presence_absence.csv for No. isolates → bucket assignment
import pandas as pd
gpa = pd.read_csv(ROARY / "gene_presence_absence.csv", low_memory=False)
n_strains = 262

def bucket(n_iso: int) -> str:
    pct = n_iso / n_strains * 100
    if pct >= 99: return "core"
    if pct >= 95: return "soft_core"
    if pct >= 15: return "shell"
    return "cloud"

cluster_bucket = dict(zip(gpa["Gene"], gpa["No. isolates"].apply(bucket)))
buckets_count = pd.Series(cluster_bucket).value_counts()
print(f"\nBucket counts: {dict(buckets_count)}")

# 3. Group representative locus_tags by their parent strain (prefix before _)
# Prokka uses strain-specific prefixes (e.g. DNMKAHCA_03629 → DNMKAHCA*)
# but we know the strain id from gpa columns.
print("\nIndexing locus → strain via GPA columns (this takes a moment) …")
locus_to_strain: dict[str, str] = {}
non_meta = [c for c in gpa.columns if c not in {
    "Gene", "Non-unique Gene name", "Annotation", "No. isolates",
    "No. sequences", "Avg sequences per isolate", "Genome Fragment",
    "Order within Fragment", "Accessory Fragment", "Accessory Order with Fragment",
    "QC", "Min group size nuc", "Max group size nuc", "Avg group size nuc",
}]
for col in non_meta:
    series = gpa[col].dropna().astype(str)
    for v in series:
        for lt in v.split("\t"):
            lt = lt.strip()
            if lt:
                locus_to_strain[lt] = col
print(f"  indexed {len(locus_to_strain):,} locus tags across {len(non_meta)} strains")

# 4. Walk each strain's .faa to fetch needed sequences
print("\nFetching representative sequences from per-strain faa files …")
needed_by_strain: dict[str, list[tuple[str, str]]] = defaultdict(list)
for cluster, rep_lt in cluster_to_rep.items():
    strain = locus_to_strain.get(rep_lt)
    if not strain:
        # fall back: try every strain
        continue
    needed_by_strain[strain].append((cluster, rep_lt))

print(f"  {len(needed_by_strain)} strains contribute representatives")

out_faa = OUT_DIR / "pangenome_reps.faa"
out_tsv = OUT_DIR / "pangenome_reps.tsv"
total = missing = 0
with out_faa.open("w", encoding="utf-8") as ofa, \
     out_tsv.open("w", encoding="utf-8") as otsv:
    otsv.write("cluster\trep_locus_tag\tstrain\tn_member\tbucket\n")
    for strain, reps in sorted(needed_by_strain.items(),
                               key=lambda x: -len(x[1])):
        faa = PROKKA / strain / f"{strain}.faa"
        if not faa.exists():
            missing += len(reps); continue
        # Build locus -> sequence index for this strain (one pass)
        idx: dict[str, list[str]] = {}
        cur_lt = None
        with faa.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip()
                if line.startswith(">"):
                    cur_lt = line[1:].split()[0]
                    idx[cur_lt] = []
                elif cur_lt is not None:
                    idx[cur_lt].append(line)
        for cluster, rep_lt in reps:
            seq_lines = idx.get(rep_lt)
            if not seq_lines:
                missing += 1; continue
            seq = "".join(seq_lines)
            ofa.write(f">{cluster}\n{seq}\n")
            otsv.write(f"{cluster}\t{rep_lt}\t{strain}\t{n_member.get(cluster, 0)}"
                       f"\t{cluster_bucket.get(cluster, '?')}\n")
            total += 1

print(f"\n  wrote {total:,} representatives  ({missing} missing)")
print(f"  → {out_faa}")
print(f"  → {out_tsv}")
print(f"  faa size: {out_faa.stat().st_size / 1e6:.1f} MB")
