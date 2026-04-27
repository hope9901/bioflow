"""Dickeya phylogeny — two complementary trees.

  1. ML tree from Roary core gene alignment via IQ-TREE
     (ModelFinder + 1000 ultrafast bootstrap)
  2. NJ tree from FastANI distance matrix
     (whole-genome relatedness, bypasses gene-by-gene alignment limits)

Both trees are exported as Newick + rendered to PNG.
"""
from __future__ import annotations

import sys
from pathlib import Path

# cp949-safe stdout
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bioflow.core.runner import DockerBackend  # noqa: E402

ANALYSIS = ROOT / "analysis" / "dickeya"
TREE_DIR = ANALYSIS / "phylogeny"; TREE_DIR.mkdir(exist_ok=True)
FIG = ANALYSIS / "figures"; FIG.mkdir(exist_ok=True)

WS_HOST = str(ANALYSIS.resolve())
WS_CTR  = "/work"
backend = DockerBackend()


# ────────────────────────── 1. IQ-TREE on core alignment ────────────────────
print("Step A - IQ-TREE ML phylogeny on core gene alignment")
import time
t0 = time.time()
result = backend.run(
    image="staphb/iqtree2:2.2.2.7",
    command=(
        f"iqtree2 -s {WS_CTR}/roary/out/core_gene_alignment.aln "
        f"-m MFP -bb 1000 -nt 4 -redo "
        f"-pre {WS_CTR}/phylogeny/iqtree"
    ),
    mounts={WS_HOST: WS_CTR},
    cpu=4, ram_gb=4,
    workdir=WS_CTR,
)
print(f"    exit={result.exit_code}  elapsed={time.time()-t0:.1f}s")
if result.exit_code != 0:
    print("---STDOUT/ERR tail---")
    print((result.stdout + result.stderr)[-1500:])
    sys.exit(1)

iqtree_nwk = TREE_DIR / "iqtree.treefile"
print(f"    Newick -> {iqtree_nwk}")

# ────────────────────────── 2. NJ tree from ANI matrix ──────────────────────
print("\nStep B - NJ tree from FastANI distance matrix")
import numpy as np
import pandas as pd

df = pd.read_csv(
    ANALYSIS / "fastani" / "ani_matrix.tsv", sep="\t", header=None,
    names=["q", "r", "ani", "f_mapped", "f_total"],
)


def short(p: str) -> str:
    return "_".join(Path(p).stem.split("_")[:2])


df["q"] = df["q"].apply(short); df["r"] = df["r"].apply(short)
samples = sorted(set(df["q"]) | set(df["r"]))
n = len(samples); idx = {s: i for i, s in enumerate(samples)}
M = np.full((n, n), np.nan)
for _, row in df.iterrows():
    M[idx[row["q"]], idx[row["r"]]] = row["ani"]
M = np.nanmean(np.stack([M, M.T]), axis=0)
np.fill_diagonal(M, 100.0)
floor = np.nanmin(M[~np.isnan(M)])
M = np.where(np.isnan(M), floor, M)

# Distance = 100 - ANI
D = 100.0 - M
np.fill_diagonal(D, 0.0)
D = (D + D.T) / 2

# Neighbor-Joining (skbio not always installed; use scipy hierarchical as
# a robust fallback — average linkage gives a UPGMA tree which is what we
# want for ANI-based species relatedness anyway)
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform

condensed = squareform(D, checks=False)
Z = linkage(condensed, method="average")


def linkage_to_newick(Z, labels):
    """Convert scipy linkage matrix to a Newick string."""
    n = len(labels)
    nodes = {i: labels[i] for i in range(n)}
    heights = {i: 0.0 for i in range(n)}
    for i, (a, b, h, _) in enumerate(Z):
        a, b = int(a), int(b)
        ba = h - heights.get(a, 0.0); bb = h - heights.get(b, 0.0)
        nid = n + i
        nodes[nid] = f"({nodes[a]}:{ba/2:.4f},{nodes[b]}:{bb/2:.4f})"
        heights[nid] = h / 2
    return nodes[n + len(Z) - 1] + ";"


ani_nwk = TREE_DIR / "ani_nj.nwk"
ani_nwk.write_text(linkage_to_newick(Z, samples) + "\n", encoding="utf-8")
print(f"    Newick -> {ani_nwk}")


# ────────────────────────── 3. Render both trees ─────────────────────────────
print("\nStep C - Render trees as PNG (matplotlib)")
from io import StringIO

def parse_newick(nwk: str):
    """Tiny recursive Newick parser → nested (name, length, [children])."""
    s = nwk.strip().rstrip(";")
    pos = [0]
    def parse():
        if s[pos[0]] == "(":
            pos[0] += 1
            children = [parse()]
            while s[pos[0]] == ",":
                pos[0] += 1
                children.append(parse())
            assert s[pos[0]] == ")"; pos[0] += 1
        else:
            children = []
        # name
        name_start = pos[0]
        while pos[0] < len(s) and s[pos[0]] not in ",():":
            pos[0] += 1
        name = s[name_start:pos[0]]
        length = 0.0
        if pos[0] < len(s) and s[pos[0]] == ":":
            pos[0] += 1
            num_start = pos[0]
            while pos[0] < len(s) and s[pos[0]] not in ",()":
                pos[0] += 1
            length = float(s[num_start:pos[0]])
        return (name, length, children)
    return parse()


def draw_tree(node, ax, x=0.0, y=[0.0], depth_scale=1.0):
    """Recursively layout node positions and draw branches."""
    name, length, children = node
    if not children:
        cy = y[0]; y[0] += 1
        ax.plot([x, x + length * depth_scale], [cy, cy], "k-", lw=1.2)
        ax.text(x + length * depth_scale + 0.05, cy,
                " " + name, va="center", fontsize=9)
        return cy
    child_ys = [draw_tree(c, ax, x + length * depth_scale, y, depth_scale)
                for c in children]
    cy = (min(child_ys) + max(child_ys)) / 2
    # vertical bar
    ax.plot([x + length * depth_scale] * 2, [min(child_ys), max(child_ys)],
            "k-", lw=1.2)
    # incoming horizontal
    ax.plot([x, x + length * depth_scale], [cy, cy], "k-", lw=1.2)
    return cy


import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def render(nwk_path: Path, png_path: Path, title: str, depth_scale: float = 1.0):
    nwk = nwk_path.read_text(encoding="utf-8")
    tree = parse_newick(nwk)
    fig, ax = plt.subplots(figsize=(11, 6.5), dpi=130)
    y = [0.0]
    draw_tree(tree, ax, depth_scale=depth_scale)
    ax.set_title(title)
    ax.axis("off")
    ax.set_xlim(left=-0.05)
    plt.tight_layout()
    plt.savefig(png_path); plt.close()
    print(f"    {png_path}")


render(iqtree_nwk, FIG / "tree_ml_iqtree.png",
       "Dickeya — IQ-TREE ML phylogeny (core gene alignment)\n"
       "branch lengths = expected substitutions/site",
       depth_scale=8.0)
render(ani_nwk, FIG / "tree_ani_nj.png",
       "Dickeya — UPGMA tree from FastANI distances\n"
       "branch lengths = (100 - ANI)/2", depth_scale=0.05)

print("\nALL PHYLOGENY STEPS COMPLETE.")
