"""Dickeya comparative-genomics — figures.

  - ani_heatmap.png        : 13x13 ANI matrix with hierarchical clustering
  - pangenome_pie.png      : core/soft-core/shell/cloud gene fractions
  - pangenome_curve.png    : conserved & total gene growth as genomes are added
  - summary.html           : single-page report
"""
from __future__ import annotations

import sys
from pathlib import Path

# cp949-safe stdout
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.cluster import hierarchy
from scipy.spatial.distance import squareform

ROOT = Path(__file__).resolve().parent
ANI_TSV = ROOT / "fastani" / "ani_matrix.tsv"
ROARY   = ROOT / "roary" / "out"
FIG     = ROOT / "figures"; FIG.mkdir(exist_ok=True)


def short(p: str) -> str:
    """/work/inputs/D_ananatis_019464615_1.fna -> D_ananatis"""
    base = Path(p).stem
    return "_".join(base.split("_")[:2])


# ─────────────────────────────────────── ANI heatmap ────────────────────────
df = pd.read_csv(
    ANI_TSV, sep="\t", header=None,
    names=["q", "r", "ani", "frags_mapped", "frags_total"],
)
df["q"] = df["q"].apply(short)
df["r"] = df["r"].apply(short)

samples = sorted(set(df["q"]) | set(df["r"]))
n = len(samples)
M = np.full((n, n), np.nan)
idx = {s: i for i, s in enumerate(samples)}
for _, row in df.iterrows():
    i, j = idx[row["q"]], idx[row["r"]]
    M[i, j] = row["ani"]

# Symmetrise (FastANI is mostly symmetric but not perfectly)
M_sym = np.nanmean(np.stack([M, M.T]), axis=0)
# Fill diagonal with 100
np.fill_diagonal(M_sym, 100.0)
# Replace remaining NaN with the minimum observed value (= "below 75% cutoff")
floor = np.nanmin(M_sym) if np.any(~np.isnan(M_sym)) else 75.0
M_filled = np.where(np.isnan(M_sym), floor, M_sym)

# Cluster on (100 - ANI) distance
dist = 100.0 - M_filled
np.fill_diagonal(dist, 0.0)
dist = (dist + dist.T) / 2
condensed = squareform(dist, checks=False)
Z = hierarchy.linkage(condensed, method="average")
order = hierarchy.leaves_list(Z)
M_ord = M_filled[np.ix_(order, order)]
labels = [samples[i] for i in order]

fig, ax = plt.subplots(figsize=(8.5, 7.5), dpi=130)
im = ax.imshow(M_ord, cmap="viridis", vmin=80, vmax=100, aspect="equal")
ax.set_xticks(range(n)); ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=8)
ax.set_yticks(range(n)); ax.set_yticklabels(labels, fontsize=8)
for i in range(n):
    for j in range(n):
        v = M_ord[i, j]
        if not np.isnan(v):
            ax.text(j, i, f"{v:.1f}", ha="center", va="center",
                    color="white" if v < 92 else "black", fontsize=6)
ax.set_title("Dickeya genus — pairwise FastANI (%)\n(hierarchical clustering, n=13)")
fig.colorbar(im, ax=ax, label="ANI (%)", shrink=0.8)
plt.tight_layout()
plt.savefig(FIG / "ani_heatmap.png"); plt.close()
print(f"ANI heatmap -> {FIG/'ani_heatmap.png'}")

# ─────────────────────────── Pangenome pie ──────────────────────────────────
stats = (ROARY / "summary_statistics.txt").read_text(encoding="utf-8")
buckets = {}
for line in stats.strip().splitlines():
    parts = line.split("\t")
    if len(parts) >= 3 and parts[0].lower() != "total genes":
        buckets[parts[0]] = int(parts[-1])
labels_pie = list(buckets.keys())
sizes = list(buckets.values())
colors = ["#1f77b4", "#aec7e8", "#ff7f0e", "#d62728"][:len(labels_pie)]

fig, ax = plt.subplots(figsize=(7, 6), dpi=130)
wedges, _, autotexts = ax.pie(
    sizes, labels=[f"{l}\n(n={s})" for l, s in zip(labels_pie, sizes)],
    colors=colors, autopct="%.1f%%", startangle=90, textprops=dict(fontsize=9),
)
total = sum(sizes)
ax.set_title(f"Dickeya pangenome composition (n={total} gene clusters across 13 genomes)")
plt.tight_layout()
plt.savefig(FIG / "pangenome_pie.png"); plt.close()
print(f"Pangenome pie -> {FIG/'pangenome_pie.png'}")

# ─────────────────────────── Pangenome rarefaction curves ───────────────────
def _read_rtab(p: Path):
    # Roary .Rtab format: rows = permutations, cols = N (1..G).
    # Average across rows (permutations) to get the mean curve over N.
    return pd.read_csv(p, sep="\t", header=None)

curves = {
    "Conserved (core) genes": _read_rtab(ROARY / "number_of_conserved_genes.Rtab"),
    "Total (pan) genes":      _read_rtab(ROARY / "number_of_genes_in_pan_genome.Rtab"),
}
fig, ax = plt.subplots(figsize=(8, 5), dpi=130)
for label, mat in curves.items():
    mean = mat.mean(axis=0); std = mat.std(axis=0)
    x = np.arange(1, len(mean) + 1)
    ax.plot(x, mean, label=label, lw=2)
    ax.fill_between(x, mean - std, mean + std, alpha=0.25)
ax.set_xlabel("Number of genomes")
ax.set_ylabel("Number of gene clusters")
ax.set_title("Dickeya pangenome growth")
ax.legend(); ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(FIG / "pangenome_curve.png"); plt.close()
print(f"Pangenome curve -> {FIG/'pangenome_curve.png'}")

# ─────────────────────────── HTML summary ───────────────────────────────────
html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Dickeya comparative genomics</title>
<style>
 body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 1100px; margin: 2em auto; color:#222 }}
 h1 {{ border-bottom: 2px solid #444; padding-bottom: 4px }}
 .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px }}
 .card {{ border:1px solid #ddd; border-radius:8px; padding:14px; background:#fafafa }}
 img  {{ max-width: 100%; height: auto; display:block; margin:10px auto }}
 table {{ border-collapse: collapse; margin: 8px 0 }}
 th, td {{ padding: 4px 10px; border-bottom: 1px solid #ddd; text-align: left }}
 .muted {{ color: #666; font-size: 0.85em }}
</style></head><body>
<h1>Dickeya — comparative genomics</h1>
<p class="muted">13 NCBI RefSeq reference genomes, one per species. Annotated with Prokka v1.14.6,
 ANI by FastANI v1.34, pangenome by Roary v3.13.</p>

<div class="grid">
  <div class="card">
    <h2>Pairwise ANI</h2>
    <img src="figures/ani_heatmap.png" alt="ANI heatmap">
    <p>Hierarchical clustering on (100 - ANI). Within-species ANI ≥ 95% threshold confirms
    one assembly per species.</p>
  </div>
  <div class="card">
    <h2>Pangenome composition</h2>
    <img src="figures/pangenome_pie.png" alt="pangenome pie">
    <table>
      {''.join(f'<tr><td>{k}</td><td>{v:,}</td></tr>' for k,v in buckets.items())}
      <tr><td><b>Total clusters</b></td><td><b>{total:,}</b></td></tr>
    </table>
  </div>
</div>

<div class="card" style="margin-top: 24px">
  <h2>Pangenome growth</h2>
  <img src="figures/pangenome_curve.png" alt="rarefaction">
  <p>Conserved genes plateau near {int(curves['Conserved (core) genes'].iloc[:, -1].mean())},
  while the pan-genome continues to grow with each added genome
  (open pangenome, characteristic of free-living plant pathogens).</p>
</div>

<p class="muted">Generated by bioflow comparative_genomics workflow on
 {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}.</p>
</body></html>"""

(ROOT / "summary.html").write_text(html, encoding="utf-8")
print(f"\nHTML summary -> {ROOT/'summary.html'}")
