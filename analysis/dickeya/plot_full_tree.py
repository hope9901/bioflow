"""Render the 262-strain ML phylogeny with species color-coding +
adjacent ABRicate-VFDB heatmap (tree-aligned)."""
from __future__ import annotations
import sys, re
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = ROOT / "analysis" / "dickeya"
GENOMES  = ANALYSIS / "genomes_full"
TREE     = ANALYSIS / "phylogeny_full" / "iqtree_full.treefile"
ABR      = ANALYSIS / "abricate_full"
FIG      = ANALYSIS / "figures"; FIG.mkdir(exist_ok=True)


def species_of(stem: str) -> str:
    f = GENOMES / f"{stem}.fna"
    with f.open() as fh: hdr = fh.readline()
    m = re.search(r"Dickeya\s+([A-Za-z]+)", hdr)
    return m.group(1) if m else "unknown"


# ── Parse Newick into a simple binary tree of (children, length, name) ──
import re as _re

def parse_newick(s: str):
    s = s.strip().rstrip(";")
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
        # read name (label or bootstrap)
        ns = pos[0]
        while pos[0] < len(s) and s[pos[0]] not in ",():":
            pos[0] += 1
        name = s[ns:pos[0]]
        length = 0.0
        if pos[0] < len(s) and s[pos[0]] == ":":
            pos[0] += 1
            ms = pos[0]
            while pos[0] < len(s) and s[pos[0]] not in ",()":
                pos[0] += 1
            length = float(s[ms:pos[0]])
        return [children, length, name]
    return parse()


def collect_leaves(node, out):
    if not node[0]: out.append(node[2]); return
    for c in node[0]: collect_leaves(c, out)


def assign_y(node, ctr=[0]):
    if not node[0]:
        node.append(ctr[0]); ctr[0] += 1; return ctr[0] - 1
    ys = [assign_y(c, ctr) for c in node[0]]
    node.append(sum(ys) / len(ys))
    return node[3]


nwk = TREE.read_text()
tree = parse_newick(nwk)
leaves = []; collect_leaves(tree, leaves)
print(f"Tree has {len(leaves)} leaves")
assign_y(tree)


# ── Render: tree on left, VFDB heatmap on right ─────────────────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import pandas as pd
import numpy as np

species = {s: species_of(s) for s in leaves}
unique_sp = sorted(set(species.values()))
sp_color = {sp: cm.tab20(i % 20) for i, sp in enumerate(unique_sp)}

# Load ABRicate VFDB results
vfdb_rows = []
for s in leaves:
    f = ABR / f"{s}.vfdb.tsv"
    if not f.exists(): continue
    try:
        df = pd.read_csv(f, sep="\t")
        if df.empty: continue
        df["sample"] = s
        vfdb_rows.append(df)
    except Exception: pass
vfdb = pd.concat(vfdb_rows, ignore_index=True) if vfdb_rows else pd.DataFrame()
top_genes = vfdb["GENE"].value_counts().head(15).index.tolist()
print(f"Top 15 VFDB genes: {top_genes}")

# Build presence (binary) matrix: leaf × gene
pa = pd.DataFrame(0, index=leaves, columns=top_genes, dtype=int)
for _, row in vfdb.iterrows():
    if row["sample"] in pa.index and row["GENE"] in pa.columns:
        pa.loc[row["sample"], row["GENE"]] = 1

# ── Plot ────────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(15, max(20, len(leaves) * 0.10)), dpi=130)
ax_tree = fig.add_axes([0.05, 0.03, 0.38, 0.95])
ax_strip = fig.add_axes([0.44, 0.03, 0.02, 0.95])
ax_heat  = fig.add_axes([0.48, 0.03, 0.45, 0.95])

# Tree drawing (recursive)
def draw(node, x=0.0, depth_scale=1.0):
    children, length, name, y = node
    if not children:
        x_end = x + max(length, 0.0001) * depth_scale
        ax_tree.plot([x, x_end], [y, y], "k-", lw=0.4)
        ax_tree.text(x_end + 0.2, y, name, va="center", fontsize=4.5,
                     color=sp_color[species_of(name)])
        return y
    cy = []
    for c in children:
        x_end = x + max(length, 0) * depth_scale
        cy.append(draw(c, x_end, depth_scale))
    yc = (min(cy) + max(cy)) / 2
    ax_tree.plot([x + max(length, 0)*depth_scale]*2, [min(cy), max(cy)],
                 "k-", lw=0.4)
    if length > 0:
        ax_tree.plot([x, x + length*depth_scale], [yc, yc], "k-", lw=0.4)
    return yc


# Auto-scale
all_blens = []
def collect_blens(n):
    if n[1] > 0: all_blens.append(n[1])
    for c in n[0]: collect_blens(c)
collect_blens(tree)
max_depth = max(all_blens) if all_blens else 1
draw(tree, depth_scale=1.0 / max_depth * 30)
ax_tree.set_xlim(-0.5, 35)
ax_tree.set_ylim(-1, len(leaves))
ax_tree.invert_yaxis()
ax_tree.axis("off")
ax_tree.set_title(
    f"Dickeya 262-strain ML phylogeny\n"
    "GTR+G, 1000 ultrafast bootstraps, "
    f"50-gene supermatrix (91,756 bp)",
    fontsize=11,
)

# Species color strip
for s in leaves:
    y = next(_y for _l, _y in zip(leaves, range(len(leaves))) if _l == s)
    ax_strip.barh(y, 1, height=1, color=sp_color[species[s]])
ax_strip.set_xlim(0, 1); ax_strip.set_ylim(-1, len(leaves))
ax_strip.invert_yaxis()
ax_strip.axis("off")

# VFDB heatmap aligned to tree leaf order
ax_heat.imshow(pa.loc[leaves, top_genes].values.astype(float),
               aspect="auto", cmap="Reds", interpolation="nearest",
               extent=(0, len(top_genes), len(leaves), 0))
ax_heat.set_xticks(np.arange(len(top_genes)) + 0.5)
ax_heat.set_xticklabels(top_genes, rotation=80, ha="right", fontsize=7)
ax_heat.set_yticks([])
ax_heat.set_title("VFDB virulome (red = present)", fontsize=9)

# Species legend
from matplotlib.patches import Patch
patches = [Patch(color=sp_color[sp], label=sp) for sp in unique_sp]
fig.legend(handles=patches, loc="upper right", bbox_to_anchor=(0.97, 0.99),
           fontsize=7, frameon=False, ncol=1)

plt.savefig(FIG / "tree_full_with_vfdb.png", bbox_inches="tight"); plt.close()
print(f"  -> {FIG/'tree_full_with_vfdb.png'}")
