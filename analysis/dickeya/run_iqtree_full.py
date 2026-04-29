"""IQ-TREE on the 262-strain × 91,756 bp supermatrix."""
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
WS_HOST  = str(ANALYSIS); WS_CTR = "/work"
backend  = DockerBackend()

print("Launching IQ-TREE 2 on 262-strain x 91,756 bp supermatrix ...")
t0 = time.time()
r = backend.run(
    image="staphb/iqtree2:2.2.2.7",
    command=(
        f"iqtree2 -s {WS_CTR}/phylogeny_full/core_supermatrix.fna "
        f"-m GTR+G -bb 1000 -nt 4 -redo "
        f"-pre {WS_CTR}/phylogeny_full/iqtree_full"
    ),
    mounts={WS_HOST: WS_CTR}, cpu=4, ram_gb=8, workdir=WS_CTR,
)
print(f"exit={r.exit_code}  elapsed={(time.time()-t0)/60:.1f}m")
if r.exit_code != 0:
    print((r.stderr or r.stdout)[-2000:])
    sys.exit(1)
print("Done.  treefile:", ANALYSIS / "phylogeny_full" / "iqtree_full.treefile")
