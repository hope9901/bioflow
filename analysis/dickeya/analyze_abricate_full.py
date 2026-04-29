"""Aggregate ABRicate × 262 × 3 DB results.

  - per-genome counts table
  - per-DB presence/absence heatmap (samples on x, genes on y), grouped by species
  - boxplot of per-genome VFDB hits by species
"""
from __future__ import annotations
import sys, re
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = ROOT / "analysis" / "dickeya"
ABR      = ANALYSIS / "abricate_full"
GENOMES  = ANALYSIS / "genomes_full"
FIG      = ANALYSIS / "figures"; FIG.mkdir(exist_ok=True)

# Build species lookup
def species_of(stem: str) -> str:
    f = GENOMES / f"{stem}.fna"
    with f.open() as fh: hdr = fh.readline()
    m = re.search(r"Dickeya\s+([A-Za-z]+)", hdr)
    return m.group(1) if m else "unknown"


samples = sorted({p.stem.rsplit(".vfdb", 1)[0]
                  for p in ABR.glob("*.vfdb.tsv")})
print(f"Aggregating {len(samples)} samples …")

DBS = ["vfdb", "card", "plasmidfinder"]
import pandas as pd, numpy as np

# Per-DB long table
long_rows = []
counts: dict[tuple[str,str], int] = {}
for s in samples:
    for db in DBS:
        f = ABR / f"{s}.{db}.tsv"
        if not f.exists(): continue
        try:
            df = pd.read_csv(f, sep="\t")
        except Exception: continue
        if df.empty:
            counts[(s, db)] = 0
            continue
        counts[(s, db)] = len(df)
        df["sample"] = s
        df["db"] = db
        long_rows.append(df)

long = pd.concat(long_rows, ignore_index=True) if long_rows else pd.DataFrame()
print(f"  {len(long):,} total hits across all DBs")
long["species"] = long["sample"].apply(species_of)

# Per-genome counts table
ct = pd.DataFrame({
    "sample": samples,
    "species": [species_of(s) for s in samples],
    "vfdb": [counts.get((s, "vfdb"), 0) for s in samples],
    "card": [counts.get((s, "card"), 0) for s in samples],
    "plasmidfinder": [counts.get((s, "plasmidfinder"), 0) for s in samples],
})
ct["total"] = ct[["vfdb","card","plasmidfinder"]].sum(axis=1)
ct.to_csv(ABR / "_summary_per_genome.tsv", sep="\t", index=False)
print(f"\nMean hits per species:")
print(ct.groupby("species")[DBS].mean().round(1).to_string())

# ── Visualisation 1: per-DB presence heatmap (gene × species) ──────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

species_order = ct.groupby("species").size().sort_values(ascending=False).index.tolist()
print(f"\nSpecies (n strains): {dict(ct.groupby('species').size())}")

for db in DBS:
    sub = long[long["db"] == db]
    if sub.empty:
        print(f"  {db}: no hits — skip")
        continue
    # Presence in each species: % of that species's strains carrying the gene
    sp_n = ct.groupby("species").size().to_dict()
    pa = pd.crosstab(sub["GENE"], sub["sample"])
    pa = (pa > 0).astype(int)
    # Aggregate to species level: % of strains in species with gene
    species_pa = pd.DataFrame(index=pa.index, columns=species_order, dtype=float)
    sample_to_sp = dict(zip(ct["sample"], ct["species"]))
    for sp in species_order:
        sp_samples = [s for s in pa.columns if sample_to_sp.get(s) == sp]
        if not sp_samples:
            species_pa[sp] = 0.0
            continue
        species_pa[sp] = pa[sp_samples].sum(axis=1) / max(len(sp_samples), 1) * 100
    # Sort genes by overall prevalence
    species_pa["_avg"] = species_pa[species_order].mean(axis=1)
    species_pa = species_pa.sort_values("_avg", ascending=False).head(40).drop(columns=["_avg"])

    fig, ax = plt.subplots(
        figsize=(max(8, 0.55 * len(species_order) + 3),
                 max(4, 0.22 * len(species_pa) + 2)),
        dpi=130,
    )
    im = ax.imshow(species_pa.values.astype(float), aspect="auto",
                   cmap="YlOrRd", vmin=0, vmax=100)
    ax.set_xticks(range(len(species_order)))
    ax.set_xticklabels(
        [f"{sp}\n(n={sp_n.get(sp,0)})" for sp in species_order],
        rotation=45, ha="right", fontsize=8,
    )
    ax.set_yticks(range(len(species_pa)))
    ax.set_yticklabels(species_pa.index, fontsize=7)
    fig.colorbar(im, ax=ax, label="% strains in species with gene", shrink=0.7)
    ax.set_title(
        f"{db.upper()} prevalence across Dickeya species "
        f"(top {len(species_pa)} genes; n_total={len(samples)} strains)"
    )
    plt.tight_layout()
    plt.savefig(FIG / f"abricate_full_{db}.png"); plt.close()
    print(f"  {db}: heatmap → {FIG/f'abricate_full_{db}.png'}")

# ── Visualisation 2: per-genome hit counts (boxplot by species) ─────────────
fig, axes = plt.subplots(1, 3, figsize=(15, 5), dpi=130, sharey=False)
for ax, db in zip(axes, DBS):
    data = [ct.loc[ct["species"]==sp, db].values for sp in species_order]
    bp = ax.boxplot(
        data, labels=species_order, showfliers=True,
        flierprops=dict(marker=".", markersize=3, alpha=0.5),
        boxprops=dict(facecolor="#aec7e8"), patch_artist=True,
    )
    ax.set_xticklabels(species_order, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel(f"{db} hits per genome")
    ax.set_title(f"{db.upper()}")
    ax.grid(axis="y", alpha=0.3)
plt.suptitle("ABRicate hits per genome — by species (n=262)")
plt.tight_layout()
plt.savefig(FIG / "abricate_full_boxplot.png"); plt.close()
print(f"\nBoxplot → {FIG/'abricate_full_boxplot.png'}")

# Quick stats
print("\nTotals:")
for db in DBS:
    n_genes = long[long["db"]==db]["GENE"].nunique() if not long.empty else 0
    n_hits  = (long["db"]==db).sum() if not long.empty else 0
    print(f"  {db:<14s}  {n_genes:5d} unique genes  {n_hits:6d} total hits  "
          f"{ct[db].mean():.1f} ± {ct[db].std():.1f} per genome")
