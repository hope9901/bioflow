"""Smoke test for the SDK-based pangenome recipe — 13 reference strains.

Quick verification that ``bioflow.recipes.pangenome`` runs end-to-end
through Docker on the small Dickeya reference set.  Should complete in
~15-25 min (13 prokka × 5 min ÷ 6 parallel + 1 roary × ~5 min).
"""
from __future__ import annotations
import sys, time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bioflow import set_workspace
from bioflow.recipes import get

ANALYSIS = ROOT / "analysis" / "dickeya"
genomes = sorted((ANALYSIS / "inputs").glob("*.fna"))
print(f"Found {len(genomes)} reference genomes")

set_workspace(ANALYSIS)
get("pangenome").show_graph()

t0 = time.time()
result = get("pangenome")(
    taxon="Dickeya",
    out_dir=ANALYSIS / "pangenome_sdk_13",
    _genome_paths=genomes,
)
print(f"\nDone in {(time.time()-t0)/60:.1f} min — result.out_dir = {result.out_dir}")
print(f"  cached={result.cached}  ok={result.ok}")
