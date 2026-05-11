"""Phase 3 integration demo — Pectobacterium genus pangenome via the SDK.

This script proves the Phase 3 roadmap goal:

    `bioflow recipe pangenome --taxon Pectobacterium` 한 줄로 우리가
    6.8시간 한 작업을 재현할 수 있어야 합니다.

…except it's now Python rather than CLI, and uses a smaller taxon cap so
it finishes in tens of minutes rather than hours.  The CLI form
``bioflow recipe run pangenome --taxon Pectobacterium --max 12`` works
identically.

What it touches end-to-end:
  * bioflow.recipes.download_taxon   (Phase 3, NCBI ingestion)
  * bioflow.recipes.pangenome        (Phase 3, parallel Prokka + Roary)
  * bioflow.recipes.ani_matrix       (Phase 3, FastANI all-vs-all)
  * bioflow.recipes.amr_vf_catalogue (Phase 3, ABRicate × N × DBs)
  * bioflow.Report                   (Phase 2E, auto-html)
  * @stage caching                   (Phase 1C — second run will be ~0 s)
  * @stage retry                     (Phase 2G — Roary auto-retries OOM)
  * parallel="auto"                  (Phase 1B — fills host CPUs)
"""
from __future__ import annotations
import sys, time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bioflow import Report, set_workspace
from bioflow.recipes import get

WS = Path(__file__).resolve().parent / "_pectobacterium_ws"
set_workspace(WS)
WS.mkdir(parents=True, exist_ok=True)

report = Report(
    title="Pectobacterium pangenome (Phase 3 integration demo)",
    out_dir=WS / "reports",
)

# ── 1. Download every Pectobacterium reference assembly ────────────────────
print("\n=== Step 1: NCBI download ===")
dl_recipe = get("download_taxon")
dl_recipe.show_graph()

t0 = time.time()
paths = dl_recipe(
    taxon="Pectobacterium",
    out_dir=WS / "genomes",
    max_genomes=12,        # small enough to finish in ~30 min total
    reference_only=True,
)
fnas = sorted((WS / "genomes").glob("*.fna"))
report.add_section(
    "1 · Genome download",
    body=f"Downloaded {len(fnas)} Pectobacterium reference assemblies "
         f"in {time.time()-t0:.0f}s.",
)

# ── 2. Pangenome (Prokka + Roary) ───────────────────────────────────────────
print("\n=== Step 2: Pangenome ===")
pan_recipe = get("pangenome")
pan_recipe.show_graph()

t0 = time.time()
pan_result = pan_recipe(
    taxon="Pectobacterium",
    out_dir=WS / "pangenome",
    _genome_paths=fnas,        # reuse downloaded set
    identity=90,
)
print(f"  Pangenome done in {(time.time()-t0)/60:.1f} min  "
      f"cached={pan_result.cached}")
report.add_section(
    "2 · Pangenome",
    body=f"Pangenome built via Roary (i=90).  "
         f"Wall: {(time.time()-t0)/60:.1f} min, cached={pan_result.cached}.",
    results=[pan_result],
)

# ── 3. ANI matrix ───────────────────────────────────────────────────────────
print("\n=== Step 3: ANI matrix ===")
ani_recipe = get("ani_matrix")
t0 = time.time()
ani_result = ani_recipe(
    out_dir=WS / "ani",
    genome_paths=fnas,
)
print(f"  ANI done in {(time.time()-t0):.0f}s  cached={ani_result.cached}")
report.add_section(
    "3 · ANI",
    body="All-vs-all FastANI matrix (genus-level genetic distance).",
    results=[ani_result],
)

# ── 4. AMR + VF + plasmid catalogue ─────────────────────────────────────────
print("\n=== Step 4: AMR + VF catalogue ===")
amr_recipe = get("amr_vf_catalogue")
t0 = time.time()
amr_results = amr_recipe(
    out_dir=WS / "abricate",
    genome_paths=fnas,
    dbs=("vfdb", "card", "plasmidfinder"),
)
print(
    f"  ABRicate done in {(time.time()-t0):.0f}s  "
    f"({len(amr_results)} runs, "
    f"{sum(r.cached for r in amr_results)} cached, "
    f"{sum(1 for r in amr_results if not r.ok)} failed)"
)
report.add_section(
    "4 · AMR + VF catalogue",
    body=f"ABRicate × {len(fnas)} genomes × 3 DBs (VFDB / CARD / "
         f"PlasmidFinder) — total {len(amr_results)} runs.",
    results=amr_results,
)

# ── 5. Final report ─────────────────────────────────────────────────────────
report_path = report.write()
print(f"\n=== Done.  Report: {report_path} ===")
