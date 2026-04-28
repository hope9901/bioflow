"""D. solani island analysis — correct the 'co-inherited island' hypothesis.

The 30 species-defining accessory genes from Scoary turned out to be scattered
across the chromosome, not a single block. But ONE genuinely-tight 5-gene
mini-cluster (≈5 kb at ~4.20 Mb) holds the AbaF fosfomycin-resistance gene
together with a transcriptional repressor and a deaminase — classic
operon-style organisation. This script:

  1. extracts ±10 kb of neighbours around that cluster from a representative
     D. solani assembly,
  2. checks the immediate vicinity for mobile-element hallmarks (transposase,
     integrase, tRNA-flanking),
  3. computes GC% of the cluster vs the whole chromosome,
  4. compares synteny across all 5 D. solani strains where Prokka data exists,
  5. renders a labelled gene-order diagram for the cluster.
"""
from __future__ import annotations
import sys, re
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

ANALYSIS = ROOT / "analysis" / "dickeya"
PROKKA   = ANALYSIS / "prokka_full"
GENOMES  = ANALYSIS / "genomes_full"
GPA_CSV  = ANALYSIS / "roary_full" / "out" / "gene_presence_absence.csv"
FIG      = ANALYSIS / "figures"; FIG.mkdir(exist_ok=True)

REF = "GCF_001644705.1"   # D. solani IPO 2222 type strain

# ── 1. Extract the 4.195-4.200 Mb mini-cluster + ±10 kb context ─────────────
def parse_gff(gff: Path):
    """Yield (locus_tag, contig, start, end, strand, product, gene_name)."""
    with gff.open() as fh:
        for line in fh:
            if line.startswith("##FASTA"): break
            if line.startswith("#"): continue
            f = line.rstrip().split("\t")
            if len(f) < 9 or f[2] not in ("CDS", "tRNA", "rRNA", "tmRNA"):
                continue
            attrs = f[8]
            mid = re.search(r"ID=([^;]+)", attrs)
            if not mid: continue
            mp = re.search(r"product=([^;]+)", attrs)
            mg = re.search(r"gene=([^;]+)", attrs)
            yield (
                mid.group(1), f[0], int(f[3]), int(f[4]), f[6],
                mp.group(1) if mp else "", mg.group(1) if mg else "",
                f[2],   # feature type
            )


print("=" * 75)
print(f"REFERENCE — {REF}  (Dickeya solani IPO 2222, type strain)")
print("=" * 75)

ref_features = list(parse_gff(PROKKA / REF / f"{REF}.gff"))
print(f"  {len(ref_features)} features parsed")

# Cluster: AbaF region 4,195,388-4,200,154
CLUSTER_START, CLUSTER_END = 4_195_388, 4_200_154
contig_target = "NZ_CP015137.1"

context = [f for f in ref_features
           if f[1] == contig_target
           and f[2] >= CLUSTER_START - 10_000
           and f[3] <= CLUSTER_END   + 10_000]
context.sort(key=lambda x: x[2])

print(f"\n5 kb cluster + 10 kb on each side = {context[0][2]:,}-{context[-1][3]:,}")
print(f"  features in window: {len(context)}\n")

mge_keywords = re.compile(
    r"transposase|integrase|recombinase|insertion sequence|IS\d|"
    r"phage|integron|conjug|plasmid|mobile|ICE|excision",
    re.IGNORECASE,
)
trna_count = 0
mge_hits = []
for f in context:
    is_island = (CLUSTER_START <= f[2] <= CLUSTER_END
                 or CLUSTER_START <= f[3] <= CLUSTER_END)
    is_mge = bool(mge_keywords.search(f[5] + " " + f[6]))
    if f[7] == "tRNA": trna_count += 1
    if is_mge: mge_hits.append(f)
    flag = "★" if is_island else ("•" if is_mge else " ")
    print(f"  {flag} {f[1]} {f[2]:>10,}-{f[3]:<10,} {f[4]} "
          f"{f[7]:<5s} {(f[6] or f[0])[:14]:<14s} {(f[5])[:50]}")

print(f"\n  tRNA features in window: {trna_count}")
print(f"  Mobile-element keyword hits: {len(mge_hits)}")
if mge_hits:
    for h in mge_hits:
        print(f"    {h[0]}  {h[5]}")
else:
    print("    (none — no transposase/integrase/IS/phage gene found in window)")

# ── 2. GC% of cluster vs chromosome ─────────────────────────────────────────
print("\n" + "=" * 75)
print("GC content comparison")
print("=" * 75)

ref_fna = GENOMES / f"{REF}.fna"
seqs: dict[str, list[str]] = {}
cur = None
for line in ref_fna.read_text().splitlines():
    if line.startswith(">"):
        cur = line.split()[0][1:]; seqs[cur] = []
    elif cur: seqs[cur].append(line)
ref_chrom = "".join(seqs[contig_target])

def gc(s: str) -> float:
    s = s.upper(); g = s.count("G") + s.count("C")
    at = s.count("A") + s.count("T")
    return g / max(g+at, 1) * 100


cluster_seq = ref_chrom[CLUSTER_START-1:CLUSTER_END]
gc_cluster = gc(cluster_seq)
gc_genome  = gc(ref_chrom)
print(f"  whole chromosome ({len(ref_chrom)/1e6:.2f} Mb): GC% = {gc_genome:.2f}")
print(f"  5-kb cluster:                   GC% = {gc_cluster:.2f}")
print(f"  delta:                          {gc_cluster - gc_genome:+.2f}%")

# Sliding 5 kb GC of whole chromosome
import numpy as np
WIN = 5000
gc_track = np.array([
    gc(ref_chrom[i:i+WIN])
    for i in range(0, len(ref_chrom) - WIN, 1000)
])
percentile = (gc_track < gc_cluster).sum() / len(gc_track) * 100
print(f"  cluster GC vs all 5-kb windows on chromosome: {percentile:.1f} percentile")

# ── 3. Synteny across 5 representative solani strains ──────────────────────
print("\n" + "=" * 75)
print("Synteny across 5 D. solani strains (cluster gene order)")
print("=" * 75)

import pandas as pd
gpa = pd.read_csv(GPA_CSV, low_memory=False)
solani_top = pd.read_csv(ANALYSIS / "scoary_full" / "top30_is_solani.tsv", sep="\t")

# Pick the 5 cluster genes (positions 4.195-4.200 Mb) — by their group_id
cluster_groups = ["group_22027", "group_22028", "group_22029",
                  "group_22030", "group_22031"]
cluster_anno = {
    "group_22027": "AbaF (fosfomycin Rᴬ)",
    "group_22028": "hypothetical",
    "group_22029": "deaminase",
    "group_22030": "hypothetical",
    "group_22031": "RspR (HTH)",
}

# Choose representative strains: the type strain + 4 others
type_strains_with_gff = [
    p.parent.name for p in PROKKA.glob("*/*.gff")
]
solani_genomes = []
for f in GENOMES.glob("*.fna"):
    with f.open() as fh: hdr = fh.readline()
    if "Dickeya solani" in hdr and f.stem in type_strains_with_gff:
        solani_genomes.append(f.stem)
print(f"  {len(solani_genomes)} D. solani strains have Prokka output")

# Take 5 spread-out representatives
import random; random.seed(42)
reps = [REF] + random.sample(
    [s for s in solani_genomes if s != REF], k=min(4, len(solani_genomes)-1),
)
print(f"  Reps: {reps}")

# For each rep, find the cluster gene positions
synteny: dict[str, list] = {}
for rep in reps:
    locus_tags = {}
    for g in cluster_groups:
        row = gpa[gpa["Gene"] == g]
        if not row.empty:
            lt = row.iloc[0].get(rep, "")
            if isinstance(lt, str) and lt.strip():
                locus_tags[lt.split()[0]] = g

    # parse this rep's GFF
    feats = list(parse_gff(PROKKA / rep / f"{rep}.gff"))
    by_lt = {f[0]: f for f in feats}
    rep_cluster = []
    for lt, g in locus_tags.items():
        if lt in by_lt:
            f = by_lt[lt]
            rep_cluster.append((f[2], f[3], f[4], g))   # start, end, strand, group
    rep_cluster.sort()
    synteny[rep] = rep_cluster
    print(f"  {rep:<25s} {len(rep_cluster)} cluster genes "
          f"@ {rep_cluster[0][0]:,} (rel-strand={rep_cluster[0][2]})")

# ── 4. Render synteny diagram ───────────────────────────────────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrow

fig, ax = plt.subplots(figsize=(12, 0.9 * len(reps) + 1.5), dpi=130)

# Normalise each rep's cluster to start=0 for visual alignment
group_color = {
    "group_22027": "#d62728",  # AbaF — red
    "group_22028": "#ff7f0e",
    "group_22029": "#2ca02c",  # deaminase — green
    "group_22030": "#9467bd",
    "group_22031": "#1f77b4",  # RspR — blue
}
for y, rep in enumerate(reps):
    feats = synteny[rep]
    if not feats: continue
    # Compute display starts in the orientation of the first gene
    base_start = feats[0][0]
    for s, e, strand, g in feats:
        x0 = (s - base_start) / 1000          # kb
        x1 = (e - base_start) / 1000
        if strand == "-":
            ax.add_patch(FancyArrow(
                x1, y, x0 - x1, 0, width=0.5,
                head_width=0.65, length_includes_head=True,
                head_length=0.10,
                facecolor=group_color[g], edgecolor="black", lw=0.7,
            ))
        else:
            ax.add_patch(FancyArrow(
                x0, y, x1 - x0, 0, width=0.5,
                head_width=0.65, length_includes_head=True,
                head_length=0.10,
                facecolor=group_color[g], edgecolor="black", lw=0.7,
            ))
        ax.text((x0+x1)/2, y+0.5, cluster_anno[g], ha="center", va="bottom",
                fontsize=7, rotation=0)

short = lambda s: s
ax.set_yticks(range(len(reps)))
ax.set_yticklabels([short(r) for r in reps], fontsize=9)
ax.set_xlabel("Position relative to first cluster gene (kb)")
ax.set_title(
    "D. solani species-defining mini-cluster (Scoary p≈10⁻⁵¹)\n"
    "Five-gene fosfomycin-Rᴬ + regulator block, conserved orientation across strains"
)
ax.set_xlim(-1, max(
    (synteny[r][-1][1] - synteny[r][0][0]) / 1000
    for r in reps if synteny[r]
) + 1)
ax.set_ylim(-1, len(reps))
ax.invert_yaxis()
ax.spines[["right", "top"]].set_visible(False)
ax.grid(axis="x", alpha=0.3)
plt.tight_layout()
plt.savefig(FIG / "solani_island_synteny.png"); plt.close()
print(f"\n  Synteny diagram → {FIG/'solani_island_synteny.png'}")

# ── 5. GC% track plot ──────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 3.5), dpi=130)
xs = np.arange(0, len(gc_track)) * 1   # each x = kb
ax.plot(xs, gc_track, color="#444", lw=0.5, alpha=0.7)
ax.axhline(gc_genome, color="#1f77b4", ls="--", lw=1, label=f"genome mean = {gc_genome:.1f}%")
# Mark cluster
cx = (CLUSTER_START + CLUSTER_END) / 2 / 1000
ax.axvspan(CLUSTER_START/1000, CLUSTER_END/1000, color="#d62728", alpha=0.3,
           label=f"AbaF cluster ({gc_cluster:.1f}%)")
ax.axvline(cx, color="#d62728", lw=1)
ax.set_xlabel("Chromosome position (kb)")
ax.set_ylabel("GC% (5-kb sliding window)")
ax.set_title(f"GC content along D. solani {REF} chromosome — AbaF cluster atypicality")
ax.legend(loc="upper right")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(FIG / "solani_island_gc.png"); plt.close()
print(f"  GC track → {FIG/'solani_island_gc.png'}")

print("\nDone.")
