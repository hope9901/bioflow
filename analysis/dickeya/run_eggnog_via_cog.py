"""COG-2024 functional enrichment of the Dickeya pangenome (eggNOG alternative).

Approach:
  1. Build a small reference DB: one representative sequence per COG
     (~5,000 seqs from the 5 GB COGorg24.faa, using cog-24.cog.csv as lookup).
  2. Build a DIAMOND DB on that small set.
  3. DIAMOND blastp our 34,629 pangenome reps → COG reps.
  4. Map best-hit subject → COG ID → functional-category letter
     (cog-24.def.tab provides COG -> 1-letter category).
  5. Compute COG-letter enrichment per pangenome bucket and plot.
"""
from __future__ import annotations
import sys, time, gzip
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bioflow.core.runner import DockerBackend  # noqa: E402

ANALYSIS = ROOT / "analysis" / "dickeya"
EGGNOG   = ANALYSIS / "eggnog"
COG_DIR  = EGGNOG / "cog_db"
RESULTS  = EGGNOG / "results"; RESULTS.mkdir(exist_ok=True)
FIG      = ANALYSIS / "figures"; FIG.mkdir(exist_ok=True)
WS_HOST  = str(ANALYSIS); WS_CTR = "/work"
backend  = DockerBackend()

# ── 1. Pick one representative protein per COG ─────────────────────────────
print("Picking one rep protein per COG …")
rep_for_cog: dict[str, str] = {}        # COG -> protein_id (WP_xxxx)
prot_to_cog: dict[str, str] = {}        # protein_id -> COG
with (COG_DIR / "cog-24.cog.csv").open("r", encoding="utf-8") as fh:
    for line in fh:
        parts = line.split(",")
        if len(parts) < 8: continue
        prot, cog = parts[2], parts[6]
        if not cog.startswith("COG"): continue
        if cog not in rep_for_cog:
            rep_for_cog[cog] = prot
        prot_to_cog[prot] = cog
print(f"  {len(rep_for_cog)} COGs, {len(prot_to_cog):,} total prot→COG mappings")

# ── 2. Build a slim FASTA with just the rep sequences ──────────────────────
slim_faa = COG_DIR / "cog_reps.faa"
needed = set(rep_for_cog.values())
print(f"\nExtracting {len(needed)} rep sequences from COGorg24.faa.gz …")
if slim_faa.exists() and slim_faa.stat().st_size > 1000:
    print(f"  cached: {slim_faa} ({slim_faa.stat().st_size/1e6:.1f} MB)")
else:
    t0 = time.time()
    written = 0
    cur_acc = None; cur_lines = []; want = False
    with gzip.open(COG_DIR / "COGorg24.faa.gz", "rt", encoding="utf-8") as fh, \
         slim_faa.open("w", encoding="utf-8") as out:
        for line in fh:
            line = line.rstrip()
            if line.startswith(">"):
                if want and cur_lines:
                    out.write(f">{cur_acc}\n" + "\n".join(cur_lines) + "\n")
                    written += 1
                cur_acc = line[1:].split()[0]
                want = cur_acc in needed
                cur_lines = []
            elif want:
                cur_lines.append(line)
        if want and cur_lines:
            out.write(f">{cur_acc}\n" + "\n".join(cur_lines) + "\n")
            written += 1
    print(f"  wrote {written:,} seqs in {(time.time()-t0)/60:.1f}m -> "
          f"{slim_faa.stat().st_size/1e6:.1f} MB")

# ── 3. Build DIAMOND DB on the slim reference ──────────────────────────────
dmnd_db = COG_DIR / "cog_reps.dmnd"
if dmnd_db.exists():
    print(f"\nDIAMOND DB cached: {dmnd_db}")
else:
    print("\nBuilding DIAMOND DB …")
    t0 = time.time()
    r = backend.run(
        image="staphb/diamond:2.1.10",
        command=(
            f"diamond makedb --in {WS_CTR}/eggnog/cog_db/cog_reps.faa "
            f"-d {WS_CTR}/eggnog/cog_db/cog_reps -p 4"
        ),
        mounts={WS_HOST: WS_CTR}, cpu=4, ram_gb=4, workdir=WS_CTR,
    )
    print(f"  exit={r.exit_code}  elapsed={(time.time()-t0)/60:.1f}m")
    if r.exit_code != 0: sys.exit(1)

# ── 4. DIAMOND blastp our pangenome reps → COG reps ────────────────────────
hits_tsv = RESULTS / "pangenome_vs_cog.tsv"
if hits_tsv.exists() and hits_tsv.stat().st_size > 1000:
    print(f"\nDIAMOND results cached: {hits_tsv}")
else:
    print("\nRunning DIAMOND blastp (8 threads) …")
    t0 = time.time()
    r = backend.run(
        image="staphb/diamond:2.1.10",
        command=(
            f"diamond blastp -q {WS_CTR}/eggnog/pangenome_reps.faa "
            f"-d {WS_CTR}/eggnog/cog_db/cog_reps "
            f"-o {WS_CTR}/eggnog/results/pangenome_vs_cog.tsv "
            f"-p 8 -k 1 -e 1e-5 "
            f"--outfmt 6 qseqid sseqid pident length evalue bitscore "
            f"--very-sensitive"
        ),
        mounts={WS_HOST: WS_CTR}, cpu=8, ram_gb=8, workdir=WS_CTR,
    )
    print(f"  exit={r.exit_code}  elapsed={(time.time()-t0)/60:.1f}m")
    if r.exit_code != 0: sys.exit(1)

# ── 5. Build COG -> category-letter dict from def.tab ──────────────────────
cog_to_cat: dict[str, str] = {}
with (COG_DIR / "cog-24.def.tab").open(encoding="utf-8") as fh:
    for line in fh:
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 2 and parts[0].startswith("COG"):
            cog_to_cat[parts[0]] = parts[1]   # column 2 = COG functional category letter(s)

# ── 6. Aggregate hits → bucket × category counts ───────────────────────────
import pandas as pd, numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm

print("\nAggregating COG categories per pangenome bucket …")
hits = pd.read_csv(
    hits_tsv, sep="\t", header=None,
    names=["query", "subject", "pident", "length", "evalue", "bitscore"],
)
hits["cog"] = hits["subject"].map(prot_to_cog)
hits["cat"] = hits["cog"].map(cog_to_cat)
print(f"  {len(hits):,} hits  /  unique queries: {hits['query'].nunique():,}")

# Buckets from extract phase
buckets = pd.read_csv(EGGNOG / "pangenome_reps.tsv", sep="\t")
hits = hits.merge(buckets, left_on="query", right_on="cluster", how="left")

# All 34K queries, with NA for unmapped
all_q = pd.DataFrame({"query": buckets["cluster"]}).merge(
    hits[["query", "cat", "bucket"]], on="query", how="left",
).merge(
    buckets[["cluster", "bucket"]].rename(columns={"cluster": "query", "bucket": "bucket_b"}),
    on="query", how="left",
)
all_q["bucket"] = all_q["bucket"].fillna(all_q["bucket_b"])

mapped_pct_by_bucket = (
    all_q.assign(mapped=all_q["cat"].notna())
         .groupby("bucket")["mapped"].mean() * 100
)
print("\nFraction of clusters mapped to a COG (per bucket):")
print(mapped_pct_by_bucket.round(1).to_string())

# Explode multi-letter categories
exploded = (
    all_q.dropna(subset=["cat", "bucket"])
         .assign(letters=lambda d: d["cat"].astype(str).apply(list))
         .explode("letters")
)
COG_NAME = {
    "J": "Translation/ribosome", "A": "RNA processing",
    "K": "Transcription",        "L": "Replication/repair",
    "B": "Chromatin",            "D": "Cell cycle/division",
    "Y": "Nuclear structure",    "V": "Defense mechanisms",
    "T": "Signal transduction",  "M": "Cell wall/membrane",
    "N": "Cell motility",        "Z": "Cytoskeleton",
    "W": "Extracellular",        "U": "Intracellular trafficking",
    "O": "Post-translational",   "X": "Mobilome (phage/IS)",
    "C": "Energy production",    "G": "Carbohydrate metabolism",
    "E": "Amino acid metabolism","F": "Nucleotide metabolism",
    "H": "Coenzyme metabolism",  "I": "Lipid metabolism",
    "P": "Inorganic ion transport", "Q": "Secondary metabolites",
    "R": "General prediction only", "S": "Function unknown",
}
exploded = exploded[exploded["letters"].isin(COG_NAME)]

counts = (
    exploded.groupby(["bucket", "letters"]).size().unstack(fill_value=0)
)
ordered = [c for c in COG_NAME if c in counts.columns]
counts = counts[ordered]
fracs = counts.div(counts.sum(axis=1), axis=0)

bucket_order = ["core", "soft_core", "shell", "cloud"]
fracs = fracs.reindex(bucket_order)

# ── 7. Stacked-bar (functional composition by bucket) ──────────────────────
fig, ax = plt.subplots(figsize=(11, 5.5), dpi=130)
colors = cm.tab20(np.linspace(0, 1, len(fracs.columns)))
bottom = np.zeros(len(fracs))
for col, color in zip(fracs.columns, colors):
    vals = fracs[col].values
    ax.bar(fracs.index, vals, bottom=bottom, label=f"{col} {COG_NAME[col]}",
           color=color, edgecolor="white", linewidth=0.4)
    for i, v in enumerate(vals):
        if v > 0.03:
            ax.text(i, bottom[i] + v/2, col, ha="center", va="center",
                    fontsize=8, color="white", fontweight="bold")
    bottom += vals
ax.set_ylabel("Fraction of COG-mapped proteins")
ax.set_title("COG functional categories per pangenome bucket\n(262-genome Dickeya — DIAMOND blastp vs COG-2024)")
ax.set_ylim(0, 1)
ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=8, frameon=False)
plt.tight_layout()
plt.savefig(FIG / "cog_stacked.png", bbox_inches="tight"); plt.close()
print(f"\n  COG stacked bar  -> {FIG/'cog_stacked.png'}")

# ── 8. Cloud-vs-core delta ─────────────────────────────────────────────────
delta = (fracs.loc["cloud"] - fracs.loc["core"]) * 100
delta_sorted = delta.sort_values()
fig, ax = plt.subplots(figsize=(8, 7), dpi=130)
colors_d = ["#d62728" if v > 0 else "#1f77b4" for v in delta_sorted.values]
labels = [f"{c} — {COG_NAME[c]}" for c in delta_sorted.index]
ax.barh(labels, delta_sorted.values, color=colors_d)
ax.axvline(0, color="black", lw=0.7)
ax.set_xlabel("Δ fraction (cloud − core), percentage points")
ax.set_title(
    "COG enrichment — which functions dominate the cloud (RED)\n"
    "vs. the conserved core (BLUE)?"
)
ax.grid(axis="x", alpha=0.3)
plt.tight_layout()
plt.savefig(FIG / "cog_delta.png"); plt.close()
print(f"  cloud-vs-core delta -> {FIG/'cog_delta.png'}")

# Tables
counts.to_csv(EGGNOG / "cog_counts_by_bucket.tsv", sep="\t")
fracs.to_csv(EGGNOG / "cog_fractions_by_bucket.tsv", sep="\t")

# Print top deltas
print("\nTop categories enriched IN THE CLOUD (vs core):")
print(f"  {'cat':<6s}{'core%':>7s}{'cloud%':>7s}{'Δpp':>7s}  description")
for cog in delta_sorted.iloc[::-1].index[:8]:
    row = fracs[cog]
    print(f"  {cog:<6s}{row['core']*100:>7.2f}{row['cloud']*100:>7.2f}"
          f"{(row['cloud']-row['core'])*100:>+7.2f}  {COG_NAME[cog]}")
print("\nTop categories DEPLETED in the cloud:")
for cog in delta_sorted.index[:6]:
    row = fracs[cog]
    print(f"  {cog:<6s}{row['core']*100:>7.2f}{row['cloud']*100:>7.2f}"
          f"{(row['cloud']-row['core'])*100:>+7.2f}  {COG_NAME[cog]}")

print("\nDone.")
