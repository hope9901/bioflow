"""Phase 1 verification — Dickeya 262-genome pangenome via the SDK.

Same workload as the session-1 ``run_full_pangenome.py`` (175 lines of
explicit ThreadPoolExecutor + DockerBackend), but expressed against the
new SDK.  Caching, parallelism, chaining, and the DAG are all absorbed
by ``@stage`` / ``@pipeline`` / ``parallel="auto"`` — so this script
collapses to roughly 15 executable lines.
"""
from __future__ import annotations
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bioflow import set_workspace
from bioflow.recipes import get

# ── Same inputs we used in session 1 ─────────────────────────────────────────
ANALYSIS = ROOT / "analysis" / "dickeya"
genomes = sorted((ANALYSIS / "genomes_full").glob("*.fna"))
print(f"Found {len(genomes)} pre-downloaded genomes")

# ── Run the recipe ──────────────────────────────────────────────────────────
set_workspace(ANALYSIS)
get("pangenome").show_graph()

result = get("pangenome")(
    taxon="Dickeya",
    out_dir=ANALYSIS / "pangenome_via_sdk",
    _genome_paths=genomes,        # skip NCBI; reuse already-downloaded set
)

print(f"\nDone — result.out_dir = {result.out_dir}")
print(f"  cached={result.cached}  ok={result.ok}")
