"""262-genome FastANI all-vs-all + ANI-based species/subspecies clustering.

Uses bioflow's DockerBackend to run FastANI in a single container call.
Output: ani_full.tsv (~70k rows) plus a heatmap-with-dendrogram figure.
"""
from __future__ import annotations
import sys, time, re
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bioflow.core.runner import DockerBackend  # noqa: E402

ANALYSIS = ROOT / "analysis" / "dickeya"
INPUTS   = ANALYSIS / "genomes_full"
OUT      = ANALYSIS / "fastani_full"; OUT.mkdir(exist_ok=True)
FIG      = ANALYSIS / "figures"; FIG.mkdir(exist_ok=True)
WS_HOST  = str(ANALYSIS); WS_CTR = "/work"
backend  = DockerBackend()

# Build genome list & species lookup table
fnas = sorted(INPUTS.glob("*.fna"))
print(f"Indexing {len(fnas)} genomes …")
species_of: dict[str, str] = {}
for f in fnas:
    acc = f.stem
    with f.open() as fh:
        hdr = fh.readline()
    m = re.search(r"Dickeya\s+([A-Za-z]+)", hdr)
    species_of[acc] = m.group(1) if m else "unknown"

species_counts = {}
for sp in species_of.values():
    species_counts[sp] = species_counts.get(sp, 0) + 1
print("Species distribution:")
for sp, n in sorted(species_counts.items(), key=lambda x: -x[1]):
    print(f"  {sp:<20s} n={n}")

list_path = OUT / "genomes.txt"
list_path.write_text(
    "\n".join(f"{WS_CTR}/genomes_full/{f.name}" for f in fnas) + "\n",
    encoding="utf-8",
)

# Run FastANI all-vs-all
ani_tsv = OUT / "ani_full.tsv"
if ani_tsv.exists() and ani_tsv.stat().st_size > 1000:
    print(f"\nFastANI cached -> {ani_tsv} ({ani_tsv.stat().st_size/1e6:.1f} MB)")
else:
    print("\nRunning FastANI 262x262 …")
    t0 = time.time()
    r = backend.run(
        image="staphb/fastani:1.34",
        command=(
            f"fastANI --ql {WS_CTR}/fastani_full/genomes.txt "
            f"--rl {WS_CTR}/fastani_full/genomes.txt "
            f"-o {WS_CTR}/fastani_full/ani_full.tsv -t 8"
        ),
        mounts={WS_HOST: WS_CTR}, cpu=8, ram_gb=12, workdir=WS_CTR,
    )
    print(f"  exit={r.exit_code}  elapsed={time.time()-t0:.1f}s")
    if r.exit_code != 0:
        print((r.stderr or r.stdout)[-1500:]); sys.exit(1)

# Load and visualise
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.cluster.hierarchy import linkage, leaves_list
from scipy.spatial.distance import squareform

df = pd.read_csv(
    ani_tsv, sep="\t", header=None,
    names=["q", "r", "ani", "f_mapped", "f_total"],
)
df["q"] = df["q"].apply(lambda p: Path(p).stem)
df["r"] = df["r"].apply(lambda p: Path(p).stem)
print(f"\nLoaded {len(df):,} pairs")

samples = sorted(set(df["q"]) | set(df["r"]))
n = len(samples); idx = {s: i for i, s in enumerate(samples)}
M = np.full((n, n), np.nan)
for _, row in df.iterrows():
    M[idx[row["q"]], idx[row["r"]]] = row["ani"]

# Symmetrise + fill
M = np.nanmean(np.stack([M, M.T]), axis=0)
np.fill_diagonal(M, 100.0)
floor = np.nanmin(M[~np.isnan(M)])
M = np.where(np.isnan(M), floor, M)

# Cluster
D = 100.0 - M
np.fill_diagonal(D, 0.0)
D = (D + D.T) / 2
Z = linkage(squareform(D, checks=False), method="average")
order = leaves_list(Z)
M_ord = M[np.ix_(order, order)]

# Species color stripe
import matplotlib.cm as cm
unique_sp = sorted(set(species_of.values()))
sp_color = {sp: cm.tab20(i % 20) for i, sp in enumerate(unique_sp)}
colors_ord = [sp_color[species_of[samples[i]]] for i in order]

fig, axes = plt.subplots(
    1, 2, figsize=(13, 11), dpi=130,
    gridspec_kw={"width_ratios": [0.04, 1]},
)
ax_strip, ax = axes

# Heatmap
im = ax.imshow(M_ord, cmap="viridis", vmin=80, vmax=100, aspect="auto")
ax.set_xticks([]); ax.set_yticks([])
ax.set_title(
    f"Dickeya — pairwise FastANI on all {n} GCF assemblies\n"
    f"({len(unique_sp)} species, hierarchical-clustered)"
)
cbar = fig.colorbar(im, ax=ax, label="ANI (%)", shrink=0.7)

# Species color stripe (left)
ax_strip.imshow(
    np.array(colors_ord).reshape(n, 1, 4), aspect="auto",
)
ax_strip.set_xticks([]); ax_strip.set_yticks([])
ax_strip.set_ylabel("species (color-coded)")

# Legend
from matplotlib.patches import Patch
patches = [Patch(color=sp_color[sp], label=f"{sp} (n={species_counts[sp]})")
           for sp in unique_sp]
fig.legend(
    handles=patches, loc="center right", bbox_to_anchor=(1.18, 0.5),
    fontsize=8, frameon=False,
)

plt.tight_layout()
plt.savefig(FIG / "ani_full_heatmap.png", bbox_inches="tight"); plt.close()
print(f"  Heatmap -> {FIG/'ani_full_heatmap.png'}")

# Save species-membership table at 95% ANI (species delineation threshold)
print("\nWithin-species ANI ranges:")
for sp in unique_sp:
    members = [s for s in samples if species_of[s] == sp]
    if len(members) < 2: continue
    midx = [idx[m] for m in members]
    sub = M[np.ix_(midx, midx)]
    np.fill_diagonal(sub, np.nan)
    print(f"  {sp:<20s} n={len(members):3d}   "
          f"min={np.nanmin(sub):.2f}  median={np.nanmedian(sub):.2f}  "
          f"max={np.nanmax(sub):.2f}")

print("\nDone.")
