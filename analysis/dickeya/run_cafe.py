"""CAFE5 on the 262-strain ML tree — VFDB gene gain/loss along the phylogeny.

Steps:
  1. Convert iqtree_full.treefile to an ultrametric tree (scale tip
     branches so every leaf is equidistant from the root, with a small
     positive minimum).  CAFE5 requires this.
  2. Build a gene-count matrix from ABRicate VFDB output: for each unique
     VFDB gene seen in any of 262 strains, count copies per strain.
     CAFE5 format:
         Desc<TAB>FamilyID<TAB>strain1<TAB>strain2 ...
  3. Run CAFE5 (-p flag = output ancestral state probabilities).
  4. Parse Base_asr.tre / Gamma_results.txt to map per-branch gain/loss
     onto the tree and render figures.
"""
from __future__ import annotations
import sys, time, re, math
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bioflow.core.runner import DockerBackend  # noqa: E402

ANALYSIS = ROOT / "analysis" / "dickeya"
ML_TREE  = ANALYSIS / "phylogeny_full" / "iqtree_full.treefile"
ABR      = ANALYSIS / "abricate_full"
GENOMES  = ANALYSIS / "genomes_full"
CAFE     = ANALYSIS / "cafe"; CAFE.mkdir(exist_ok=True)
FIG      = ANALYSIS / "figures"; FIG.mkdir(exist_ok=True)
WS_HOST  = str(ANALYSIS); WS_CTR = "/work"
backend  = DockerBackend()

# ── 1. Newick parser/serializer + ultrametric conversion ─────────────────────
class Node:
    __slots__ = ("name", "length", "children", "parent")
    def __init__(self, name="", length=0.0):
        self.name, self.length = name, length
        self.children: list["Node"] = []
        self.parent: "Node | None" = None


def parse_newick(s: str) -> Node:
    s = s.strip().rstrip(";")
    pos = [0]
    def parse() -> Node:
        n = Node()
        if s[pos[0]] == "(":
            pos[0] += 1
            n.children.append(parse()); n.children[-1].parent = n
            while s[pos[0]] == ",":
                pos[0] += 1
                n.children.append(parse()); n.children[-1].parent = n
            assert s[pos[0]] == ")"; pos[0] += 1
        # name (or bootstrap)
        ns = pos[0]
        while pos[0] < len(s) and s[pos[0]] not in ",():":
            pos[0] += 1
        n.name = s[ns:pos[0]]
        if pos[0] < len(s) and s[pos[0]] == ":":
            pos[0] += 1
            ms = pos[0]
            while pos[0] < len(s) and s[pos[0]] not in ",()":
                pos[0] += 1
            n.length = float(s[ms:pos[0]])
        return n
    return parse()


def to_newick(n: Node, rounding: int = 6) -> str:
    if n.children:
        inner = ",".join(to_newick(c, rounding) for c in n.children)
        s = f"({inner}){n.name}"
    else:
        s = n.name
    if n.length is not None:
        s += f":{round(n.length, rounding):.{rounding}f}"
    return s


def make_ultrametric(root: Node) -> Node:
    """Scale tip branches so all leaves are equidistant from the root.
    Uses the 'extend tip' method: compute max root-to-leaf depth, then
    add (max_depth - own_depth) to each tip's branch length."""
    # 1st pass: depth from root for every node
    depth: dict[int, float] = {}
    def rec(n: Node, d: float):
        d2 = d + max(n.length, 0.0)
        depth[id(n)] = d2
        for c in n.children: rec(c, d2)
    # root depth = 0 (don't include root branch)
    depth[id(root)] = 0.0
    for c in root.children: rec(c, 0.0)
    # max tip depth
    leaves = []
    def collect(n: Node):
        if not n.children: leaves.append(n)
        else:
            for c in n.children: collect(c)
    collect(root)
    max_depth = max(depth[id(l)] for l in leaves)
    # extend tips
    for l in leaves:
        l.length += (max_depth - depth[id(l)])
    return root


# Load + ultrametric
nwk = ML_TREE.read_text().strip()
tree = parse_newick(nwk)
make_ultrametric(tree)

# Sanity check
def root_to_leaves(n: Node, d=0.0, out=None):
    if out is None: out = {}
    d2 = d + max(n.length, 0.0)
    if not n.children:
        out[n.name] = d2
    else:
        for c in n.children: root_to_leaves(c, d2, out)
    return out


# Skip the root's own branch length
sub_lens: dict[str, float] = {}
for c in tree.children:
    sub_lens.update(root_to_leaves(c, 0.0))
print(f"Ultrametric depths — min={min(sub_lens.values()):.6f}  "
      f"max={max(sub_lens.values()):.6f}  "
      f"all-equal: {abs(max(sub_lens.values())-min(sub_lens.values()))<1e-6}")

# CAFE wants integer branch lengths often, or just real-valued; we'll
# rescale to a 0-100 'time' axis for readability and apply small min branch.
target_root_depth = 100.0
scale = target_root_depth / max(sub_lens.values())
def scale_node(n: Node):
    n.length *= scale
    for c in n.children: scale_node(c)
scale_node(tree)

# Strip bootstrap labels from internal-node names — CAFE's Newick parser
# doesn't accept them (it interprets them as taxa).  Keep leaf names only.
def strip_internal_names(n: Node):
    if n.children:
        n.name = ""
        for c in n.children: strip_internal_names(c)
strip_internal_names(tree)

# Add a tiny epsilon to any zero branches (CAFE rejects 0-length internal
# branches)
EPS = 0.001
def fix_zero(n: Node):
    if n.length is not None and n.length < EPS:
        n.length = EPS
    for c in n.children: fix_zero(c)
for c in tree.children: fix_zero(c)

ULTRA = CAFE / "tree_ultrametric.nwk"
ULTRA.write_text(to_newick(tree, rounding=4) + ";\n", encoding="utf-8")
print(f"Wrote ultrametric tree -> {ULTRA}")

# Get the ordered leaf names from the tree (so the count matrix matches)
LEAVES: list[str] = []
def walk(n: Node):
    if not n.children: LEAVES.append(n.name)
    else:
        for c in n.children: walk(c)
walk(tree)
print(f"  {len(LEAVES)} leaves")

# ── 2. Build VFDB gene-count matrix from ABRicate output ────────────────────
import pandas as pd
print("\nReading ABRicate VFDB output for all 262 strains …")
all_vfdb = []
for s in LEAVES:
    f = ABR / f"{s}.vfdb.tsv"
    if not f.exists(): continue
    try:
        df = pd.read_csv(f, sep="\t")
        if df.empty: continue
        df["sample"] = s
        all_vfdb.append(df)
    except Exception:
        pass
vfdb = pd.concat(all_vfdb, ignore_index=True) if all_vfdb else pd.DataFrame()
print(f"  {len(vfdb):,} hits across {vfdb['sample'].nunique()} strains")

# Counts: rows = gene, cols = strain
counts = (
    vfdb.groupby(["GENE", "sample"]).size()
    .unstack(fill_value=0).astype(int)
)
# Add any missing strains as zero columns
for s in LEAVES:
    if s not in counts.columns:
        counts[s] = 0
counts = counts.reindex(columns=LEAVES)
print(f"  count matrix: {counts.shape[0]} genes × {counts.shape[1]} strains")

# CAFE5 input format
cafe_in = CAFE / "vfdb_counts.tsv"
with cafe_in.open("w", encoding="utf-8") as fh:
    fh.write("Desc\tFamily ID\t" + "\t".join(LEAVES) + "\n")
    for gene, row in counts.iterrows():
        # CAFE5 family ID can't contain whitespace — replace if needed
        fid = re.sub(r"\W+", "_", gene)
        fh.write(f"VFDB\t{fid}\t" + "\t".join(str(int(x)) for x in row) + "\n")
print(f"Wrote count matrix -> {cafe_in}")

# ── 3. Run CAFE5 ─────────────────────────────────────────────────────────────
print("\nLaunching CAFE5 …")
out_dir = CAFE / "results"
if out_dir.exists():
    import shutil; shutil.rmtree(out_dir)
out_dir.mkdir()

t0 = time.time()
r = backend.run(
    image="quay.io/biocontainers/cafe:5.1.0--h5ca1c30_1",
    command=(
        f"cafe5 "
        f"-i {WS_CTR}/cafe/vfdb_counts.tsv "
        f"-t {WS_CTR}/cafe/tree_ultrametric.nwk "
        f"-o {WS_CTR}/cafe/results "
        f"-c 4 -p"
    ),
    mounts={WS_HOST: WS_CTR}, cpu=4, ram_gb=8, workdir=WS_CTR,
)
print(f"  exit={r.exit_code}  elapsed={(time.time()-t0)/60:.1f}m")
if r.exit_code != 0:
    print((r.stderr or r.stdout)[-2500:])
    sys.exit(1)

# ── 4. Inspect outputs ──────────────────────────────────────────────────────
print("\nCAFE5 outputs:")
for p in sorted(out_dir.iterdir()):
    print(f"  {p.name}  ({p.stat().st_size:,} bytes)")
print("\nDone — see analysis/dickeya/cafe/results/.")
