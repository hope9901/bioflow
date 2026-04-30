"""Render CAFE5 gain/loss inference on the 262-strain phylogeny.

  - Tree with branches colour-encoded by net gene-family change
    (red = expansion / blue = contraction / grey = unchanged)
  - Bar chart of per-family expansion/contraction events across the tree
  - Detailed view of significant families (hcp, hcp1) — count at each leaf
"""
from __future__ import annotations
import sys, re
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = ROOT / "analysis" / "dickeya"
GENOMES  = ANALYSIS / "genomes_full"
RES      = ANALYSIS / "cafe" / "results"
FIG      = ANALYSIS / "figures"; FIG.mkdir(exist_ok=True)


def species_of(stem: str) -> str:
    f = GENOMES / f"{stem}.fna"
    with f.open() as fh: hdr = fh.readline()
    m = re.search(r"Dickeya\s+([A-Za-z]+)", hdr)
    return m.group(1) if m else "unknown"

import pandas as pd, numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm

# ── 1. Per-node total gain/loss across all VFDB families ─────────────────────
clade = pd.read_csv(RES / "Base_clade_results.txt", sep="\t")
clade.columns = [c.lstrip("#") for c in clade.columns]
print(f"Per-clade table: {len(clade)} nodes")
print("Top expanders/contractors:")
clade["delta"] = clade["Increase"] - clade["Decrease"]
print(clade.sort_values("delta").head(8).to_string())
print("...")
print(clade.sort_values("delta").tail(8).to_string())

# Map node label like "GCF_xxx<N>" -> taxon id N
def label_to_id(s: str) -> int:
    m = re.search(r"<(\d+)>$", str(s))
    return int(m.group(1)) if m else -1


clade["node_id"] = clade["Taxon_ID"].map(label_to_id)
clade["leaf_name"] = clade["Taxon_ID"].apply(
    lambda s: re.sub(r"<\d+>$", "", str(s)) if "GCF_" in str(s) else None
)
node_change = dict(zip(clade["node_id"], zip(clade["Increase"], clade["Decrease"])))

# ── 2. Parse the CAFE-annotated tree (Base_asr.tre) ──────────────────────────
# CAFE writes Newick with internal node labels like _1, _2, ...
# Use first tree (any single family is fine — node IDs are shared).
asr = (RES / "Base_asr.tre").read_text()
# Each line: BEGIN; ... TREE family = (...);
trees = re.findall(r"TREE \S+ = (.+);", asr)
print(f"\nASR tree records: {len(trees)}")

class Node:
    __slots__ = ("label", "length", "children", "asr_count", "node_id", "x", "y")
    def __init__(self):
        self.label = ""; self.length = 0.0
        self.children: list["Node"] = []
        self.asr_count = 0; self.node_id = -1
        self.x = 0.0; self.y = 0.0


def parse_asr_newick(s: str) -> Node:
    s = s.strip().rstrip(";").lstrip()
    pos = [0]
    def parse() -> Node:
        n = Node()
        if s[pos[0]] == "(":
            pos[0] += 1
            n.children.append(parse())
            while s[pos[0]] == ",":
                pos[0] += 1
                n.children.append(parse())
            assert s[pos[0]] == ")"; pos[0] += 1
        # Label: GCF_xxx<NID>_count or just <NID>_count
        ns = pos[0]
        while pos[0] < len(s) and s[pos[0]] not in ",():":
            pos[0] += 1
        raw = s[ns:pos[0]]
        # leaf format: GCF_xxx<NID>_COUNT
        # internal:    <NID>_COUNT
        m_inner = re.search(r"<(\d+)>_(\d+)$", raw)
        if m_inner:
            n.node_id = int(m_inner.group(1))
            n.asr_count = int(m_inner.group(2))
            n.label = raw[:m_inner.start()] if "GCF_" in raw else ""
        else:
            n.label = raw
        if pos[0] < len(s) and s[pos[0]] == ":":
            pos[0] += 1
            ms = pos[0]
            while pos[0] < len(s) and s[pos[0]] not in ",()":
                pos[0] += 1
            n.length = float(s[ms:pos[0]])
        return n
    return parse()


# ── 3. Build a 'consensus' tree using any family's topology + node IDs ─────
# We'll use the first family's tree just for topology and per-node IDs.
tree = parse_asr_newick(trees[0])

leaves = []
def collect(n):
    if not n.children: leaves.append(n)
    else:
        for c in n.children: collect(c)
collect(tree)
print(f"Tree leaves: {len(leaves)}")


# ── 4. Layout + render: tree with per-node total gain colored ───────────────
def layout(n, ctr=[0]):
    if not n.children:
        n.y = ctr[0]; ctr[0] += 1
    else:
        for c in n.children: layout(c, ctr)
        n.y = sum(c.y for c in n.children) / len(n.children)
    return n.y


def assign_x(n, x=0.0):
    n.x = x
    for c in n.children: assign_x(c, x + max(c.length, 0))


layout(tree); assign_x(tree)

# Total tree depth for x-axis
def max_depth(n):
    if not n.children: return n.x
    return max(max_depth(c) for c in n.children)
depth = max_depth(tree)


fig, axes = plt.subplots(1, 2, figsize=(13, 18), dpi=120,
                         gridspec_kw={"width_ratios": [1.5, 1]})
ax_tree, ax_bars = axes

# Compute per-node net change & magnitude
def total_change(nid):
    inc, dec = node_change.get(nid, (0, 0))
    return inc - dec, inc + dec


# Draw tree with branches colored by net change
def draw(n):
    if not n.children: return
    for c in n.children:
        net, _ = total_change(c.node_id)
        if net > 0:
            col = "#d62728"; lw = 0.8 + min(net, 4) * 0.4
        elif net < 0:
            col = "#1f77b4"; lw = 0.8 + min(-net, 4) * 0.4
        else:
            col = "#666"; lw = 0.4
        ax_tree.plot([n.x, c.x], [c.y, c.y], color=col, lw=lw)
    # vertical
    ax_tree.plot([n.x] * 2,
                 [min(c.y for c in n.children), max(c.y for c in n.children)],
                 color="#666", lw=0.4)
    for c in n.children:
        draw(c)


draw(tree)

# Leaf labels
unique_sp = sorted(set(species_of(l.label) for l in leaves))
sp_color = {sp: cm.tab20(i % 20) for i, sp in enumerate(unique_sp)}
for l in leaves:
    sp = species_of(l.label)
    ax_tree.text(l.x + 1, l.y, sp, va="center", fontsize=4.5,
                 color=sp_color[sp])

# Mark internal nodes with significant change (sum > 1 across all families)
for nid, (inc, dec) in node_change.items():
    total = inc + dec
    if total >= 2:   # interesting nodes
        # find the node in the tree
        def find(n, target):
            if n.node_id == target: return n
            for c in n.children:
                r = find(c, target)
                if r: return r
            return None
        node = find(tree, nid)
        if node and not node.children:
            continue   # leaves already labeled
        if node:
            net = inc - dec
            ax_tree.plot(node.x, node.y, "o",
                         color="#d62728" if net > 0 else "#1f77b4",
                         ms=4 + total * 1.0, mec="black", mew=0.4)

ax_tree.set_xlim(-2, depth * 1.15)
ax_tree.set_ylim(-1, len(leaves))
ax_tree.invert_yaxis()
ax_tree.axis("off")
ax_tree.set_title("Dickeya 262-strain ML tree — VFDB gain (red) / loss (blue)\n"
                  "Per-branch net change across all 20 VFDB families",
                  fontsize=11)

# ── 5. Right panel: per-family event totals ─────────────────────────────────
fam = pd.read_csv(RES / "Base_family_results.txt", sep="\t")
fam.columns = [c.lstrip("#") for c in fam.columns]
# Family-level event counts: sum of all per-node Increases/Decreases for
# that family. Need Base_change.tab.
chg = pd.read_csv(RES / "Base_change.tab", sep="\t")
# rows = families, cols = nodes; values = change at that node
chg_index = chg.iloc[:, 0]
chg_data = chg.iloc[:, 1:]
gains = (chg_data > 0).sum(axis=1)
losses = (chg_data < 0).sum(axis=1)
events = pd.DataFrame({
    "family": chg_index,
    "gains": gains.values,
    "losses": losses.values,
}).sort_values("gains", ascending=True)

y = np.arange(len(events))
ax_bars.barh(y, events["gains"], color="#d62728", label="gains", height=0.8)
ax_bars.barh(y, -events["losses"], color="#1f77b4", label="losses", height=0.8)

# Mark significant
sig_set = set(fam[fam["Significant at 0.05"] == "y"]["FamilyID"])
for i, fname in enumerate(events["family"]):
    if fname in sig_set:
        ax_bars.text(events.iloc[i]["gains"] + 1, y[i], "★",
                     fontsize=12, va="center", color="#d62728")
ax_bars.set_yticks(y)
ax_bars.set_yticklabels(events["family"], fontsize=9)
ax_bars.axvline(0, color="black", lw=0.5)
ax_bars.set_xlabel("← lost      events along all branches      gained →")
ax_bars.set_title("VFDB families: total events on tree\n(★ = CAFE p<0.05 — non-random rate)",
                  fontsize=10)
ax_bars.grid(axis="x", alpha=0.3)
ax_bars.legend(loc="lower right", fontsize=9)

plt.tight_layout()
plt.savefig(FIG / "cafe_vfdb_tree.png", bbox_inches="tight"); plt.close()
print(f"\n  Tree+events panel -> {FIG/'cafe_vfdb_tree.png'}")

# ── 6. hcp / hcp1 detail figure ─────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), dpi=130, sharey=True)
counts = pd.read_csv(RES / "Base_count.tab", sep="\t", index_col=0)
counts.columns = [re.sub(r"<\d+>$", "", c) for c in counts.columns]

for ax, fam_name in zip(axes, ["hcp", "hcp1"]):
    if fam_name not in counts.index: continue
    sample_to_sp = {l.label: species_of(l.label) for l in leaves}
    leaf_counts = pd.DataFrame({
        "sample": [c for c in counts.columns if c in sample_to_sp],
    })
    leaf_counts["count"] = counts.loc[fam_name, leaf_counts["sample"]].values
    leaf_counts["species"] = leaf_counts["sample"].map(sample_to_sp)

    species_order = leaf_counts["species"].value_counts().index.tolist()
    means = leaf_counts.groupby("species")["count"].mean().reindex(species_order)
    sds   = leaf_counts.groupby("species")["count"].std().reindex(species_order)
    ax.bar(species_order, means.values,
           yerr=sds.fillna(0).values, capsize=3,
           color=[sp_color[s] for s in species_order])
    ax.set_xticklabels(species_order, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel(f"{fam_name} copies per genome")
    ax.set_title(f"{fam_name} — CAFE p<0.05 (non-random across phylogeny)",
                 fontsize=10)
    ax.grid(axis="y", alpha=0.3)
plt.suptitle("Significant T6SS-related VFDB families with non-random gain/loss",
             fontsize=11)
plt.tight_layout()
plt.savefig(FIG / "cafe_hcp_detail.png"); plt.close()
print(f"  hcp detail -> {FIG/'cafe_hcp_detail.png'}")

print("\nDone.")
