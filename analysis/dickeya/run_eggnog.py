"""eggNOG-mapper on the 262-genome Dickeya pangenome representatives.

Input  : analysis/dickeya/eggnog/pangenome_reps.faa  (34,629 sequences)
DB     : analysis/dickeya/eggnog/db/                 (eggnog.db + .dmnd)
Output : analysis/dickeya/eggnog/results/            (TSV annotations)

Then computes COG-category enrichment of each pangenome bucket
(core / soft_core / shell / cloud) and produces the final figure.
"""
from __future__ import annotations
import sys, time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bioflow.core.runner import DockerBackend  # noqa: E402

ANALYSIS = ROOT / "analysis" / "dickeya"
EGGNOG   = ANALYSIS / "eggnog"
RESULTS  = EGGNOG / "results"; RESULTS.mkdir(exist_ok=True)
FIG      = ANALYSIS / "figures"; FIG.mkdir(exist_ok=True)

WS_HOST = str(ANALYSIS); WS_CTR = "/work"
backend = DockerBackend()

# ── 1. Run emapper (skip if already done) ──────────────────────────────────
ann_tsv = RESULTS / "pangenome.emapper.annotations"
if ann_tsv.exists() and ann_tsv.stat().st_size > 1000:
    print(f"emapper output cached: {ann_tsv}")
else:
    print("Running eggNOG-mapper (Diamond mode, 8 cpu) …")
    t0 = time.time()
    r = backend.run(
        image="quay.io/biocontainers/eggnog-mapper:2.1.12--pyhdfd78af_0",
        command=(
            f"emapper.py -i {WS_CTR}/eggnog/pangenome_reps.faa "
            f"--itype proteins --output pangenome "
            f"--output_dir {WS_CTR}/eggnog/results "
            f"--data_dir {WS_CTR}/eggnog/db "
            f"--cpu 8 --override --no_annot N --tax_scope auto"
        ),
        mounts={WS_HOST: WS_CTR}, cpu=8, ram_gb=20, workdir=WS_CTR,
        timeout=7200,
    )
    print(f"  exit={r.exit_code}  elapsed={(time.time()-t0)/60:.1f}m")
    if r.exit_code != 0:
        print((r.stderr or r.stdout)[-2000:]); sys.exit(1)

# ── 2. Parse annotations + cross-join with bucket assignments ──────────────
import pandas as pd
import numpy as np

print("\nParsing emapper TSV …")
# emapper writes a leading '#' on the header line + comments → skip
ann = pd.read_csv(ann_tsv, sep="\t", comment="#", header=None)
# column names from emapper docs (12-col annotation format)
colnames = [
    "query", "seed_ortholog", "evalue", "score",
    "eggNOG_OGs", "max_annot_lvl", "COG_category", "Description",
    "Preferred_name", "GOs", "EC", "KEGG_ko", "KEGG_Pathway",
    "KEGG_Module", "KEGG_Reaction", "KEGG_rclass", "BRITE",
    "KEGG_TC", "CAZy", "BiGG_Reaction", "PFAMs",
]
# emapper's true header lives in a comment line that begins with '#query'
# Try to find it for accurate naming
header_line = None
with ann_tsv.open() as fh:
    for ln in fh:
        if ln.startswith("#query"):
            header_line = ln.lstrip("#").rstrip().split("\t")
            break
if header_line and len(header_line) == ann.shape[1]:
    ann.columns = header_line
elif len(colnames) >= ann.shape[1]:
    ann.columns = colnames[:ann.shape[1]]

print(f"  {len(ann):,} annotated representatives "
      f"(of 34,629 total = {len(ann)/34629*100:.1f}%)")

# Bucket assignment from extract phase
buckets = pd.read_csv(EGGNOG / "pangenome_reps.tsv", sep="\t")
ann_full = ann.merge(buckets, left_on="query", right_on="cluster", how="left")
print(f"  bucket distribution among annotated: "
      f"{ann_full['bucket'].value_counts().to_dict()}")

# ── 3. COG-category enrichment per bucket ──────────────────────────────────
# COG codes (24 categories) — keep only single-letter codes
COG_NAME = {
    "J": "Translation/ribosome",   "A": "RNA processing",
    "K": "Transcription",          "L": "Replication/repair",
    "B": "Chromatin structure",    "D": "Cell cycle/division",
    "Y": "Nuclear structure",      "V": "Defense mechanisms",
    "T": "Signal transduction",    "M": "Cell wall/membrane",
    "N": "Cell motility",          "Z": "Cytoskeleton",
    "W": "Extracellular",          "U": "Intracellular trafficking",
    "O": "Post-translational",     "X": "Mobilome (phages, transposons)",
    "C": "Energy production",      "G": "Carbohydrate metabolism",
    "E": "Amino acid metabolism",  "F": "Nucleotide metabolism",
    "H": "Coenzyme metabolism",    "I": "Lipid metabolism",
    "P": "Inorganic ion transport", "Q": "Secondary metabolites",
    "R": "General prediction only", "S": "Function unknown",
}

# Each protein may have a multi-letter COG code (e.g. "MO"); split & expand
exploded = (
    ann_full[["bucket", "COG_category"]]
    .dropna(subset=["bucket", "COG_category"])
    .assign(letters=lambda d: d["COG_category"].astype(str).apply(list))
    .explode("letters")
)
# Drop unknown / hyphen
exploded = exploded[exploded["letters"].isin(COG_NAME)]

# Counts per (bucket, letter)
counts = (
    exploded.groupby(["bucket", "letters"]).size()
            .unstack(fill_value=0)
)
# Order columns so important categories come first
ordered = [c for c in COG_NAME if c in counts.columns]
counts = counts[ordered]
# Convert to fractions per bucket
fracs = counts.div(counts.sum(axis=1), axis=0)

# ── 4. Plot stacked-bar (bucket-stratified COG fractions) ──────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm

bucket_order = ["core", "soft_core", "shell", "cloud"]
fracs = fracs.reindex(bucket_order)

fig, ax = plt.subplots(figsize=(11, 5.5), dpi=130)
colors = cm.tab20(np.linspace(0, 1, len(fracs.columns)))
bottom = np.zeros(len(fracs))
for col, color in zip(fracs.columns, colors):
    vals = fracs[col].values
    ax.bar(fracs.index, vals, bottom=bottom, label=f"{col} {COG_NAME[col]}",
           color=color, edgecolor="white", linewidth=0.4)
    # Show percentage label only for slices > 3%
    for i, v in enumerate(vals):
        if v > 0.03:
            ax.text(i, bottom[i] + v/2, col, ha="center", va="center",
                    fontsize=8, color="white", fontweight="bold")
    bottom += vals

ax.set_ylabel("Fraction of annotated proteins")
ax.set_title("COG functional categories: pangenome bucket comparison\n(262-genome Dickeya pangenome — 34,629 clusters)")
ax.set_ylim(0, 1)
ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5),
          fontsize=8, frameon=False)
plt.tight_layout()
plt.savefig(FIG / "eggnog_cog_stacked.png", bbox_inches="tight"); plt.close()
print(f"\n  COG stacked bar -> {FIG/'eggnog_cog_stacked.png'}")

# ── 5. Cloud-vs-core enrichment (delta plot) ──────────────────────────────
delta = (fracs.loc["cloud"] - fracs.loc["core"]) * 100   # percentage points
delta_sorted = delta.sort_values()

fig, ax = plt.subplots(figsize=(8, 7), dpi=130)
colors_d = ["#d62728" if v > 0 else "#1f77b4" for v in delta_sorted.values]
labels = [f"{c} — {COG_NAME[c]}" for c in delta_sorted.index]
ax.barh(labels, delta_sorted.values, color=colors_d)
ax.axvline(0, color="black", lw=0.7)
ax.set_xlabel("Δ fraction (cloud − core) in percentage points")
ax.set_title(
    "COG enrichment: which functions are over-represented\n"
    "in cloud genes vs the conserved core?"
)
ax.grid(axis="x", alpha=0.3)
plt.tight_layout()
plt.savefig(FIG / "eggnog_cog_delta.png"); plt.close()
print(f"  cloud-vs-core delta -> {FIG/'eggnog_cog_delta.png'}")

# ── 6. Save tables ─────────────────────────────────────────────────────────
counts.to_csv(EGGNOG / "cog_counts_by_bucket.tsv", sep="\t")
fracs.to_csv(EGGNOG / "cog_fractions_by_bucket.tsv", sep="\t")

# Print numerical summary
print("\nCOG fractions per bucket (top-overrepresented in cloud first):")
print(f"  {'COG':<6s}{'core':>7s}{'soft':>7s}{'shell':>7s}{'cloud':>7s}  description")
for cog in delta_sorted.index[::-1][:10]:
    row = fracs[cog]
    print(f"  {cog:<6s}{row['core']:>7.3f}{row['soft_core']:>7.3f}"
          f"{row['shell']:>7.3f}{row['cloud']:>7.3f}  {COG_NAME[cog]}")

print("\nDone.")
